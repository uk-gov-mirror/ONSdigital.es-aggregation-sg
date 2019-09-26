# es-aggregation-sg

## Wranglers

### Calculate Enterprise Reference Count  Wrangler

The wrangler is responsible for preparing the data, invoking the lambda and then sending the data downstream along with the respective notification messages (SNS).

Steps performed:

    - Retrieves data From S3 bucket
    - Filters the data by current period
    - Invokes method lambda
    - Puts the aggregated data onto the SQS queue
    - Sends SNS message

### Calculate County Totals Wrangler

The wrangler is responsible for preparing the data, invoking the method lambda and sending the data downstream along with
the respective notification messages (SNS).

Steps performed:

    - Retrieves data from S3 bucket
    - Filters the data by current period
    - Invokes method lambda
    - Puts the aggregated data onto the SQS queue
    - Sends SNS notification

## Methods

### Calculate Enterprise Reference Count Method

**Name of Lambda:** aggregation_entref_method

**Summary:** This method is responsible for grouping the data by county, region and period. It then aggregates on enterprise_reference creating a count and then renames the column accordingly.

**Inputs:** The method requires the data which is output from imputation but filtered by the current period (done by wrangler) and contains all the following columns: county, region, period and enterprise_ref.

**Outputs:** A JSON string which contains the aggregated data and the enterprise_ref count.

### Calculate County Totals Method

**Name of Lambda:** aggregation_county_method

**Summary:** Generates a JSON dataset, grouped by region, county and period, with the Q608 totals (sum) as a new
column called 'county_total'.

**Inputs:** This method requires the data that is output from imputation but filtered by the current period (done by wrangler)
and contains all the following columns: county, region, period and enterprise_ref

**Outputs:** A JSON string which contains the aggregated data and the county totals.

### Calculate Top Two Method

**Name of Lambda:** aggregation_top2_wrangler

**Summary:** Takes a DataFrame in json format and uses the columns period, county and Q608_total to calculate the highest and second highest total within each period/county combination. These are then appended as two new columns. Finally, the DataFrame is re-converted to json and sent on via SQS.

**Inputs:** This method requires a DataFrame in json format containing the following integer columns: "county", "period" and "Q608_total"

**Outputs:** A JSON object of the input DataFrame with the following two columns appended: "largest_contributor" and "second_largest_contributor"

