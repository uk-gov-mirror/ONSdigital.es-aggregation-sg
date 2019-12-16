import json
import unittest.mock as mock

import pandas as pd
from botocore.response import StreamingBody
from moto import mock_sqs

import aggregation_column_wrangler


class MockContext:
    aws_request_id = 66


context_object = MockContext()


class TestCountyWranglerMethods:
    @classmethod
    def setup_class(cls):
        cls.mock_os_patcher = mock.patch.dict(
            "os.environ",
            {
                "bucket_name": "mock-bucket",
                "out_file_name": "mock-file",
                "sqs_queue_url": "mock-queue-url",
                "checkpoint": "mockpoint",
                "sns_topic_arn": "mock-topic-arn",
                "sqs_message_group_id": "mock-message-id",
                "method_name": "mock-method",
                "incoming_message_group": "yes",
                'in_file_name': 'esFree'
            }
        )

        cls.mock_os_patcher.start()

    @classmethod
    def teardown_class(cls):
        # Stop the mocking of the os stuff
        cls.mock_os_patcher.stop()

    @mock.patch("aggregation_column_wrangler.aws_functions.save_data")
    @mock.patch("aggregation_column_wrangler.boto3.client")
    @mock.patch("aggregation_column_wrangler.aws_functions.read_dataframe_from_s3")
    def test_happy_path(self, mock_s3_return, mock_lambda, mock_sqs):
        invoke_data = ''
        with open("tests/fixtures/imp_output_test.json", 'r') as input_file:
            invoke_data = input_file.read()
        with open("tests/fixtures/imp_output_test.json") as input_file:
            input_data = json.load(input_file)

            mock_s3_return.return_value = pd.DataFrame(input_data)
            mock_lambda.return_value.invoke.return_value.get.return_value.read.\
                return_value.decode.return_value = json.dumps({"data": invoke_data,
                                                               "success": True})
            returned_value = aggregation_column_wrangler.\
                lambda_handler({
                    "RuntimeVariables":
                        {"period": 6666,
                         "aggregation_type": "sum",
                         "aggregated_column": "county",
                         "cell_total_column": "county_total",
                         "total_column": "Q608_total",
                         "additional_aggregated_column": "region",
                         "period_column": "period"
                         }
                }, context_object)

            mock_sqs.return_value = {"Messages": [{"Body": json.dumps(input_data),
                                                   "ReceiptHandle": "String"}]}

            assert "success" in returned_value
            assert returned_value["success"] is True

    @mock.patch("aggregation_column_wrangler.boto3")
    @mock.patch("aggregation_column_wrangler.boto3.client")
    @mock.patch("aggregation_column_wrangler.aws_functions.read_dataframe_from_s3")
    def test_wrangler_general_exception(self, mock_s3_return, mock_client, mock_boto):
        mock_s3_return.side_effect = Exception()
        response = aggregation_column_wrangler.\
            lambda_handler({
                "RuntimeVariables":
                    {"period": 6666,
                     "aggregation_type": "sum",
                     "aggregated_column": "county",
                     "cell_total_column": "county_total",
                     "total_column": "Q608_total",
                     "additional_aggregated_column": "region",
                     "period_column": "period"
                     }
            }, context_object)

        assert "success" in response
        assert response["success"] is False
        assert """General Error""" in response["error"]

    def test_marshmallow_raises_wrangler_exception(self):
        """
        Testing the marshmallow raises an exception in wrangler.
        :return: None.
        """
        # Removing the strata_column to allow for test of missing parameter
        aggregation_column_wrangler.os.environ.pop("method_name")

        response = aggregation_column_wrangler.\
            lambda_handler({
                "RuntimeVariables":
                    {"period": 6666,
                     "aggregation_type": "sum",
                     "aggregated_column": "county",
                     "cell_total_column": "county_total",
                     "total_column": "Q608_total",
                     "additional_aggregated_column": "region",
                     "period_column": "period"
                     }
            }, context_object)

        aggregation_column_wrangler.os.environ["method_name"] = "mock_method"
        assert """Error validating environment params:""" in response["error"]

    @mock.patch("aggregation_column_wrangler.boto3")
    @mock.patch("aggregation_column_wrangler.boto3.client")
    @mock.patch("aggregation_column_wrangler.aws_functions.read_dataframe_from_s3")
    def test_wrangler_key_error(self, mock_s3_return, mock_client, mock_boto):
        with open("tests/fixtures/imp_output_test.json") as input_file:
            input_data = json.load(input_file)
            mock_s3_return.side_effect = KeyError()
            mock_s3_return.return_value = pd.DataFrame(input_data)
            response = aggregation_column_wrangler.\
                lambda_handler({
                    "RuntimeVariables":
                        {"period": 6666,
                         "aggregation_type": "sum",
                         "aggregated_column": "county",
                         "cell_total_column": "county_total",
                         "total_column": "Q608_total",
                         "additional_aggregated_column": "region",
                         "period_column": "period"
                         }
                }, context_object)

            assert "success" in response
            assert response["success"] is False
            assert """Key Error""" in response["error"]

    @mock.patch("aggregation_column_wrangler.aws_functions.save_data")
    @mock.patch("aggregation_column_wrangler.boto3.client")
    @mock.patch("aggregation_column_wrangler.aws_functions.read_dataframe_from_s3")
    def test_incomplete_read(self, mock_s3_return, mock_client, mock_sqs):
        with open("tests/fixtures/imp_output_test.json") as input_file:
            input_data = json.load(input_file)
            mock_s3_return.return_value = pd.DataFrame(input_data)

            mock_client_object = mock.Mock()
            mock_client.return_value = mock_client_object
            mock_client_object.invoke.return_value = {
                "Payload": StreamingBody(input_file, 123456)
            }
            response = aggregation_column_wrangler.\
                lambda_handler({
                    "RuntimeVariables":
                        {"period": 6666,
                         "aggregation_type": "sum",
                         "aggregated_column": "county",
                         "cell_total_column": "county_total",
                         "total_column": "Q608_total",
                         "additional_aggregated_column": "region",
                         "period_column": "period"
                         }
                }, context_object)

            assert "success" in response
            assert response["success"] is False
            assert """Incomplete Lambda response""" in response["error"]

    def test_client_error_exception(self):
        with mock.patch("aggregation_column_wrangler."
                        "aws_functions.read_dataframe_from_s3") as mock_s3:
            with open("tests/fixtures/imp_output_test.json", "r") as file:
                mock_content = file.read()
                mock_s3.side_effect = KeyError()
                mock_s3.return_value = mock_content

            response = aggregation_column_wrangler.\
                lambda_handler({
                    "RuntimeVariables":
                        {"period": 6666,
                         "aggregation_type": "sum",
                         "aggregated_column": "county",
                         "cell_total_column": "county_total",
                         "total_column": "Q608_total",
                         "additional_aggregated_column": "region",
                         "period_column": "period"
                         }
                }, context_object)

        assert response['error'].__contains__("""Key Error""")

    @mock_sqs
    def test_fail_to_get_from_sqs(self):
        response = aggregation_column_wrangler.\
                lambda_handler({
                    "RuntimeVariables":
                        {"period": 6666,
                         "aggregation_type": "sum",
                         "aggregated_column": "county",
                         "cell_total_column": "county_total",
                         "total_column": "Q608_total",
                         "additional_aggregated_column": "region",
                         "period_column": "period"
                         }
                }, context_object)

        assert "success" in response
        assert response["success"] is False
        assert response["error"].__contains__("""AWS Error""")

    @mock.patch("aggregation_column_wrangler.aws_functions.save_data")
    @mock.patch("aggregation_column_wrangler.boto3.client")
    @mock.patch("aggregation_column_wrangler.aws_functions.read_dataframe_from_s3")
    def test_method_error(self, mock_s3_return, mock_lambda, mock_sqs):

        with open("tests/fixtures/imp_output_test.json") as input_file:
            input_data = json.load(input_file)

            mock_s3_return.return_value = pd.DataFrame(input_data)

            mock_lambda.return_value.invoke.return_value.get.return_value \
                .read.return_value.decode.return_value = json.dumps(
                    {"success": False, "error": "This is an error message"})

            returned_value = aggregation_column_wrangler.\
                lambda_handler({
                    "RuntimeVariables":
                        {"period": 6666,
                         "aggregation_type": "sum",
                         "aggregated_column": "county",
                         "cell_total_column": "county_total",
                         "total_column": "Q608_total",
                         "additional_aggregated_column": "region",
                         "period_column": "period"
                         }
                }, context_object)

            mock_sqs.return_value = {"Messages": [{"Body": json.dumps(input_data),
                                                   "ReceiptHandle": "String"}]}

            assert "success" in returned_value
            assert returned_value["success"] is False
            assert returned_value["error"].__contains__("""This is an error message""")