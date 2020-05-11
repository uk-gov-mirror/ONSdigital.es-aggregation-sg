import json
import logging
import os

import boto3
import pandas as pd
from es_aws_functions import aws_functions, exception_classes, general_functions
from marshmallow import Schema, fields


class EnvironmentSchema(Schema):
    checkpoint = fields.Str(required=True)
    bucket_name = fields.Str(required=True)
    method_name = fields.Str(required=True)


class RuntimeSchema(Schema):
    total_columns = fields.List(fields.String, required=True)
    factors_parameters = fields.Dict(required=True)
    in_file_name = fields.Str(required=True)
    incoming_message_group_id = fields.Str(required=True)
    location = fields.Str(required=True)
    out_file_name_bricks = fields.Str(required=True)
    out_file_name_region = fields.Str(required=True)
    sns_topic_arn = fields.Str(required=True)
    queue_url = fields.Str(required=True)
    unique_identifier = fields.List(fields.String, required=True)


class FactorsSchema(Schema):
    region_column = fields.Str(required=True)
    regionless_code = fields.Int(required=True)


def lambda_handler(event, context):
    """
    The wrangler converts the data from JSON format into a dataframe and then edits data.
    This process consolidates 36 columns of data down to 12 and adds brick_type, then
    creates two outputs. One with the GB region added and one with a
    consolidated brick_type.

    :param event: Contains all the variables which are required for the specific run.
    :param context: N/A

    :return:  Success & Checkpoint/Error - Type: JSON
    """
    current_module = "Pre Aggregation Data Wrangler."
    error_message = ""
    logger = logging.getLogger("Pre Aggregation Data Wrangler")
    logger.setLevel(10)
    # Define run_id outside of try block
    run_id = 0
    try:

        logger.info("Starting " + current_module)

        # Retrieve run_id before input validation
        # Because it is used in exception handling
        run_id = event["RuntimeVariables"]["run_id"]

        sqs = boto3.client("sqs", region_name="eu-west-2")
        lambda_client = boto3.client("lambda", region_name="eu-west-2")

        environment_variables, errors = EnvironmentSchema().load(os.environ)
        if errors:
            logger.error(f"Error validating environment params: {errors}")
            raise ValueError(f"Error validating environment params: {errors}")

        runtime_variables, errors = RuntimeSchema().load(event["RuntimeVariables"])
        if errors:
            logger.error(f"Error validating runtime params: {errors}")
            raise ValueError(f"Error validating runtime params: {errors}")

        factors_parameters = runtime_variables["factors_parameters"]

        factors, errors = FactorsSchema().load(factors_parameters["RuntimeVariables"])
        if errors:
            logger.error(f"Error validating runtime params: {errors}")
            raise ValueError(f"Error validating runtime params: {errors}")

        logger.info("Validated parameters.")

        # Environment Variables
        checkpoint = environment_variables["checkpoint"]
        bucket_name = environment_variables["bucket_name"]
        method_name = environment_variables["method_name"]

        # Runtime Variables
        column_list = runtime_variables["total_columns"]
        in_file_name = runtime_variables["in_file_name"]
        incoming_message_group_id = runtime_variables["incoming_message_group_id"]
        location = runtime_variables["location"]
        out_file_name_bricks = runtime_variables["out_file_name_bricks"]
        out_file_name_region = runtime_variables["out_file_name_region"]
        region_column = factors["region_column"]
        regionless_code = factors["regionless_code"]
        sns_topic_arn = runtime_variables["sns_topic_arn"]
        sqs_queue_url = runtime_variables["queue_url"]
        unique_identifier = runtime_variables["unique_identifier"]

        logger.info("Retrieved configuration variables.")

        # Pulls In Data.
        data, receipt_handler = aws_functions.get_dataframe(sqs_queue_url, bucket_name,
                                                            in_file_name,
                                                            incoming_message_group_id,
                                                            location)

        logger.info("Succesfully retrieved data.")

        brick_type = {
            "clay": 3,
            "concrete": 2,
            "sandlime": 4
        }
        # Prune rows that contain no data
        questions_list = [brick + "_" + column
                          for column in column_list
                          for brick in brick_type.keys()]
        data["zero_data"] = data.apply(
            lambda x: do_check(x, questions_list), axis=1)
        data = data[~data["zero_data"]]

        new_type = 1  # This number represents Clay & Sandlime Combined

        # Identify The Brick Type Of The Row.
        data[unique_identifier[0]] = data.apply(
            lambda x: calculate_row_type(x, brick_type, column_list), axis=1)

        # Collate Each Rows 12 Good Brick Type Columns And 24 Empty Columns Down
        # Into 12 With The Same Name.
        data = data.apply(lambda x: sum_columns(x, brick_type, column_list,
                                                unique_identifier), axis=1)

        # Old Columns With Brick Type In The Name Are Dropped.
        for question in questions_list:
            data.drop([question], axis=1, inplace=True)

        # Add GB Region For Aggregation By Region.
        logger.info("Creating File For Aggregation By Region.")
        data_region = data.to_json(orient="records")

        payload = {
            "RuntimeVariables": {
                "data": json.loads(data_region),
                "regionless_code": regionless_code,
                "region_column": region_column,
                "run_id": run_id
            }
        }

        # Pass the data for processing (adding of the regionless region.
        gb_region_data = lambda_client.invoke(
            FunctionName=method_name,
            Payload=json.dumps(payload)
        )
        logger.info("Succesfully invoked method.")

        json_response = json.loads(gb_region_data.get("Payload").read().decode("UTF-8"))
        logger.info("JSON extracted from method response.")

        if not json_response["success"]:
            raise exception_classes.MethodFailure(json_response["error"])

        region_dataframe = pd.DataFrame(json.loads(json_response["data"]))

        totals_dict = {total_column: "sum" for total_column in column_list}

        data_region = region_dataframe.groupby(
            unique_identifier[1:]).agg(
            totals_dict).reset_index()

        region_output = data_region.to_json(orient="records")

        aws_functions.save_to_s3(bucket_name, out_file_name_region,
                                 region_output, location)

        logger.info("Successfully sent data to s3")

        # Collate Brick Types Clay And Sand Lime Into A Single Type And Add To Data
        # For Aggregation By Brick Type.
        logger.info("Creating File For Aggregation By Brick Type.")
        data_brick = data.copy()

        data = data[data[unique_identifier[0]] != brick_type["concrete"]]
        data[unique_identifier[0]] = new_type

        data_brick = pd.concat([data_brick, data])

        brick_dataframe = data_brick.groupby(unique_identifier[0:2]
                                             ).agg(totals_dict).reset_index()

        brick_output = brick_dataframe.to_json(orient="records")
        aws_functions.save_to_s3(bucket_name, out_file_name_bricks,
                                 brick_output, location)

        logger.info("Successfully sent data to s3")

        if receipt_handler:
            sqs.delete_message(QueueUrl=sqs_queue_url, ReceiptHandle=receipt_handler)

        logger.info(aws_functions.send_sns_message(checkpoint, sns_topic_arn,
                                                   "Pre Aggregation."))

        logger.info("Succesfully sent message to sns")

    except Exception as e:
        error_message = general_functions.handle_exception(e, current_module,
                                                           run_id, context)
    finally:
        if (len(error_message)) > 0:
            logger.error(error_message)
            raise exception_classes.LambdaFailure(error_message)

    logger.info("Successfully completed module: " + current_module)

    return {"success": True, "checkpoint": checkpoint}


def calculate_row_type(row, brick_type, column_list):
    """
    Takes a row and adds up all columns of the current type.
    If there is data we know it is the current type.

    :param row: Contains all data. - Row.
    :param brick_type: Dictionary of the possible brick types. - Dict.
    :param column_list: List of the columns that need to be added. - List.

    :return:  brick_type - Int.
    """

    for check_type in brick_type.keys():
        total_for_type = 0

        for current_column in column_list:
            total_for_type += row[check_type + "_" + current_column]

        if total_for_type > 0:
            return brick_type[check_type]


def sum_columns(row, brick_type, column_list, unique_identifier):
    """
    Takes a row and the columns with data, then adds that data to the generically
    named columns.

    :param row: Contains all data. - Row.
    :param brick_type: Dictionary of the possible brick types. - Dict.
    :param column_list: List of the columns that need to be added to. - List.
    :param unique_identifier: List of columns to make each row unique. - List.

    :return:  Updated row. - Row.
    """

    for check_type in brick_type.keys():
        if row[unique_identifier[0]] == brick_type[check_type]:
            for current_column in column_list:
                row[current_column] = row[check_type + "_" + current_column]

    return row


def do_check(row, questions_list):
    """
    Prunes rows that contain 0 for all question values.
    Returns true if all of the cols are == 0

    :param row: Contains all data. - Row.
    :param questions_list: List of question columns

    :return:  Bool. False if any question col had a value
    """
    total_data = 0
    for question in questions_list:
        total_data += row[question]
    if total_data == 0:
        return True
    else:
        return False
