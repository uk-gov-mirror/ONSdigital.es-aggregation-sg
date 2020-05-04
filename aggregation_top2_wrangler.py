import json
import logging
import os

import boto3
from es_aws_functions import aws_functions, exception_classes, general_functions
from marshmallow import Schema, fields


class EnvironmentSchema(Schema):
    """
    Schema to ensure that environment variables are present and in the
    correct format.
    :return: None
    """
    bucket_name = fields.Str(required=True)
    checkpoint = fields.Str(required=True)
    method_name = fields.Str(required=True)


class RuntimeSchema(Schema):
    additional_aggregated_column = fields.Str(required=True)
    aggregated_column = fields.Str(required=True)
    in_file_name = fields.Str(required=True)
    location = fields.Str(required=True)
    out_file_name = fields.Str(required=True)
    outgoing_message_group_id = fields.Str(required=True)
    sns_topic_arn = fields.Str(required=True)
    queue_url = fields.Str(required=True)
    top1_column = fields.Str(required=True)
    top2_column = fields.Str(required=True)
    total_columns = fields.List(fields.String, required=True)


def lambda_handler(event, context):
    """
    This wrangler is used to prepare data for the calculate top two
    statistical method.
    The method requires a dataframe which must contain the columns specified by:
    - aggregated column
    - additional aggregated column
    - total columns

    :param event: {"RuntimeVariables":{
        aggregated_column - A column to aggregate by. e.g. Enterprise_Reference.
        additional_aggregated_column - A column to aggregate by. e.g. Region.
        total_columns - The names of the columns to produce aggregations for.
        top1_column - The prefix for the largest_contibutor column
        top2_column - The prefix for the second_largest_contibutor column
    }}
    :param context: N/A
    :return: {"success": True, "checkpoint": 4}
            or LambdaFailure exception
    """
    current_module = "Aggregation Calc Top Two - Wrangler."
    logger = logging.getLogger()
    logger.setLevel(10)
    error_message = ""
    checkpoint = 4
    # Define run_id outside of try block
    run_id = 0
    try:
        logger.info("Starting " + current_module)
        # Retrieve run_id before input validation
        # Because it is used in exception handling
        run_id = event["RuntimeVariables"]["run_id"]

        # Needs to be declared inside of the lambda handler
        lambda_client = boto3.client("lambda", region_name="eu-west-2")
        logger.info("Setting-up environment configs")

        environment_variables, errors = EnvironmentSchema().load(os.environ)
        if errors:
            logger.error(f"Error validating environment params: {errors}")
            raise ValueError(f"Error validating environment params: {errors}")

        runtime_variables, errors = RuntimeSchema().load(event["RuntimeVariables"])
        if errors:
            logger.error(f"Error validating runtime params: {errors}")
            raise ValueError(f"Error validating runtime params: {errors}")

        logger.info("Validated parameters.")

        # Environment Variables
        bucket_name = environment_variables["bucket_name"]
        checkpoint = environment_variables["checkpoint"]
        method_name = environment_variables["method_name"]

        # Runtime Variables
        aggregated_column = runtime_variables["aggregated_column"]
        additional_aggregated_column = runtime_variables["additional_aggregated_column"]
        in_file_name = runtime_variables["in_file_name"]
        location = runtime_variables["location"]
        out_file_name = runtime_variables["out_file_name"]
        outgoing_message_group_id = runtime_variables["outgoing_message_group_id"]
        sns_topic_arn = runtime_variables["sns_topic_arn"]
        sqs_queue_url = runtime_variables["queue_url"]
        top1_column = runtime_variables["top1_column"]
        top2_column = runtime_variables["top2_column"]
        total_columns = runtime_variables["total_columns"]

        logger.info("Retrieved configuration variables.")

        # Read from S3 bucket
        data = aws_functions.read_dataframe_from_s3(bucket_name, in_file_name, location)
        logger.info("Completed reading data from s3")

        # Serialise data
        logger.info("Converting dataframe to json.")
        prepared_data = data.to_json(orient="records")

        # Invoke aggregation top2 method
        logger.info("Invoking the statistical method.")

        json_payload = {
            "RuntimeVariables": {
                "data": prepared_data,
                "total_columns": total_columns,
                "additional_aggregated_column": additional_aggregated_column,
                "aggregated_column": aggregated_column,
                "top1_column": top1_column,
                "top2_column": top2_column,
                "run_id": run_id
            }
        }

        top2 = lambda_client.invoke(FunctionName=method_name,
                                    Payload=json.dumps(json_payload))

        json_response = json.loads(top2.get("Payload").read().decode("utf-8"))

        if not json_response["success"]:
            raise exception_classes.MethodFailure(json_response["error"])

        # Sending output to SQS, notice to SNS
        logger.info("Sending function response downstream.")
        aws_functions.save_data(bucket_name, out_file_name,
                                json_response["data"], sqs_queue_url,
                                outgoing_message_group_id, location)
        logger.info("Successfully sent the data to S3")
        aws_functions.send_sns_message(checkpoint, sns_topic_arn, "Aggregation - Top 2.")
        logger.info("Successfully sent the SNS message")

    except Exception as e:
        error_message = general_functions.handle_exception(e, current_module,
                                                           run_id, context)
    finally:
        if (len(error_message)) > 0:
            logger.error(error_message)
            raise exception_classes.LambdaFailure(error_message)

    logger.info("Successfully completed module: " + current_module)

    return {"success": True, "checkpoint": checkpoint}
