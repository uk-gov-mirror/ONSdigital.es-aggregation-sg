import json
import logging

import marshmallow
import pandas as pd


class EnvironSchema(marshmallow.Schema):
    """
    Class to set up the environment variables schema.
    """
    input_json = marshmallow.fields.Str(required=True)
    total_column = marshmallow.fields.Str(required=True)
    additional_aggregated_column = marshmallow.fields.Str(required=True)
    aggregated_column = marshmallow.fields.Str(required=True)
    cell_total_column = marshmallow.fields.Str(required=True)
    aggregation_type = marshmallow.fields.Str(required=True)


def lambda_handler(event, context):
    """
    Generates a JSON dataset, grouped by the given aggregated_column(e.g.county) with
     the given total_column(e.g.Q608_total) aggregated by the given aggregation_type
     (e.g.Sum) as a new column called cell_total_column(e.g.county_total).

    :param event: {
        aggregated_column - A column to aggregate by. e.g. Enterprise_Reference.
        additional_aggregated_column - A column to aggregate by. e.g. Region.
        aggregation_type - How we wish to do the aggregation. e.g. sum, count, nunique.
        total_column - The column with the sum of the data.
        cell_total_column - Name of column to rename total_column.
    }

    :param context: N/A
    :return: Success - {"success": True/False, "data"/"error": "JSON String"/"Message"}
    """
    current_module = "Aggregation by column - Method"
    error_message = ""
    log_message = ""
    logger = logging.getLogger("Aggregation")
    output_json = ""
    try:
        logger.info("Aggregation by column - Method begun.")

        # Set up Environment variables Schema.
        schema = EnvironSchema(strict=False)
        config, errors = schema.load(event)
        if errors:
            raise ValueError(f"Error validating environment parameters: {errors}")

        input_json = json.loads(config["input_json"])
        total_column = config["total_column"]
        additional_aggregated_column = config["additional_aggregated_column"]
        aggregated_column = config["aggregated_column"]
        cell_total_column = config["cell_total_column"]
        aggregation_type = config["aggregation_type"]

        input_dataframe = pd.DataFrame(input_json)

        logger.info("JSON data converted to DataFrame.")

        county_agg = input_dataframe.groupby([additional_aggregated_column,
                                              aggregated_column])

        agg_by_county_output = county_agg.agg({total_column: aggregation_type})\
            .reset_index()

        agg_by_county_output.rename(
            columns={total_column: cell_total_column},
            inplace=True
        )

        logger.info("County totals successfully calculated.")

        output_json = agg_by_county_output.to_json(orient='records')
        final_output = {"data": output_json}
        logger.info("DataFrame converted to JSON for output.")

    except KeyError as e:
        error_message = ("Key Error in "
                         + current_module + " |- "
                         + str(e.args) + " | Request ID: "
                         + str(context.aws_request_id))

        log_message = error_message + " | Line: " + str(e.__traceback__.tb_lineno)

    except Exception as e:
        error_message = ("General Error in "
                         + current_module + " ("
                         + str(type(e)) + ") |- "
                         + str(e.args) + " | Request ID: "
                         + str(context.aws_request_id))

        log_message = error_message + " | Line: " + str(e.__traceback__.tb_lineno)

    finally:
        if (len(error_message)) > 0:
            logger.error(log_message)
            return {"success": False, "error": error_message}

    logger.info("Successfully completed module: " + current_module)
    final_output['success'] = True
    return final_output
