import boto3
import pandas as pd
import logging

from botocore.exceptions import IncompleteReadError, ClientError


class NoDataInQueueError(Exception):
    pass


# Set up clients
s3 = boto3.resource('s3')
sqs = boto3.client('sqs', region_name='eu-west-2')
sns = boto3.client('sns', region_name='eu-west-2')
lambda_client = boto3.client('lambda', region_name="eu-west-2")


def lambda_handler(event, context):
    """
        This method requires a dataframe which must contain the input columns...
         - period
         - county
         - Q608_total
        ... and the two output columns...
         - largest_contributor
         - second_largest contributor

        It loops through each county (by period) and records largest & second largest value
        against each record in the group.

        :param event: N/A
        :param context: N/A
        :return: Success - Dataframe, checkpoint
    """
    current_module = "Aggregation Calc Top Two - Method"
    logger = logging.getLogger()
    error_message = ''
    log_message = ''
    response_json = None

    logger.info("Starting " + current_module)

    try:
        # NB: No environ vars used at this time, so schema and marshmallow class removed.

        logger.info("Converting input json to dataframe")
        input_json = event
        input_dataframe = pd.DataFrame(input_json)

        logger.info("Invoking calc_top_two function on input dataframe")
        response = calc_top_two(input_dataframe)

        logger.info("Converting output dataframe to json")
        response_json = response.to_json(orient='records')

    except NoDataInQueueError as e:
        error_message = "There was no data in sqs queue in:  " \
                        + current_module + " |-  | Request ID: " \
                        + str(context['aws_request_id'])

        log_message = error_message + " | Line: " + str(e.__traceback__.tb_lineno)

    except AttributeError as e:
        error_message = "Bad data encountered in " \
                        + current_module + " |- " \
                        + str(e.args) + " | Request ID: " \
                        + str(context['aws_request_id'])

        log_message = error_message + " | Line: " + str(e.__traceback__.tb_lineno)

    except ValueError as e:
        error_message = "Parameter validation error" \
                        + current_module + " |- " \
                        + str(e.args) + " | Request ID: " \
                        + str(context['aws_request_id'])

        log_message = error_message + " | Line: " + str(e.__traceback__.tb_lineno)

    except ClientError as e:
        error_message = "AWS Error (" \
                        + str(e.response['Error']['Code']) + ") " \
                        + current_module + " |- " \
                        + str(e.args) + " | Request ID: " \
                        + str(context['aws_request_id'])

        log_message = error_message + " | Line: " + str(e.__traceback__.tb_lineno)

    except KeyError as e:
        error_message = "Key Error in " \
                        + current_module + " |- " \
                        + str(e.args) + " | Request ID: " \
                        + str(context['aws_request_id'])

        log_message = error_message + " | Line: " + str(e.__traceback__.tb_lineno)

    except IncompleteReadError as e:
        error_message = "Incomplete Lambda response encountered in " \
                        + current_module + " |- " \
                        + str(e.args) + " | Request ID: " \
                        + str(context['aws_request_id'])

        log_message = error_message + " | Line: " + str(e.__traceback__.tb_lineno)

    except Exception as e:
        error_message = "General Error in " \
                        + current_module + " (" \
                        + str(type(e)) + ") |- " \
                        + str(e.args) + " | Request ID: " \
                        + str(context['aws_request_id'])

        log_message = error_message + " | Line: " + str(e.__traceback__.tb_lineno)

    finally:
        if(len(error_message)) > 0:
            logger.error(log_message)
            return {"success": False, "error": error_message}

    logger.info("Returning the output json")
    logger.info("Successfully completed module: " + current_module)

    return response_json


def calc_top_two(data):
    # NB: No need for try/except as called from inside try clause in lambda_handler
    # Set logger
    logger = logging.getLogger()
    logger.info("Executing function: calc_top_two")

    # Ensure additional columns are zeroed (Belt n Braces)
    data['largest_contributor'] = 0
    data['second_largest contributor'] = 0
    secondary_value = 0

    # Create unique list of periods in data
    period_list = list(data.period.unique())

    # Get unique periods
    for period in period_list:
        county_list = []
        temp_county_list = data.loc[(data['period'] == period)]['county'].tolist()
        logger.info("Processing period " + str(period))

        # Make County unique
        for temp_county in temp_county_list:
            if temp_county not in county_list:
                county_list.append(temp_county)

            # Loop through each county (by period) and update largest & second largest value
            for county in county_list:
                logger.info("...Processing county " + str(county))

                tot = data.loc[(data['period'] == period)][['Q608_total', 'county']]

                tot2 = tot.loc[(tot['county'] == county)]

                sorted_dataframe = tot2.sort_values(by=['Q608_total'], ascending=False)

                sorted_dataframe = sorted_dataframe.reset_index(drop=True)

                top_two = sorted_dataframe.head(2)

                primary_value = top_two['Q608_total'].iloc[0]
                if top_two.shape[0] >= 2:
                    secondary_value = top_two['Q608_total'].iloc[1]

                data.loc[(data['county'] == county) & (data['period'] == period),
                         'largest_contributor'] = primary_value
                data.loc[(data['county'] == county) & (data['period'] == period),
                         'second_largest_contributor'] = secondary_value

    logger.info("Returning the output data")
    logger.info("Successfully completed function: calc_top_two")

    return data[['county', 'region', 'period', 'largest_contributor', 'second_largest_contributor']]



