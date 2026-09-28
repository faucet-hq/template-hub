# faucet-hq/salesforce

Core Sales and Service Cloud objects through **Bulk API 2.0 query jobs** on
REST API **v67.0**
([Bulk API 2.0 queries](https://developer.salesforce.com/docs/atlas.en-us.api_asynch.meta/api_asynch/queries.htm)).
Bulk API 2.0 is Salesforce's documented path for exporting large record sets:
one asynchronous job per object returns CSV result sets, instead of thousands
of paged REST queries.

```bash
faucet run --source faucet-hq/salesforce --sink faucet-hq/bigquery \
  --param salesforce_url=https://acme.my.salesforce.com \
  --param salesforce_client_id="$SF_CLIENT_ID" --param salesforce_client_secret="$SF_CLIENT_SECRET" \
  --param bq_project=my-project --param bq_sa_key="$BQ_SA_KEY" \
  --overlay my-state.yaml          # a state: block, so each object resumes
```

## Authentication and permissions

OAuth 2.0 **client credentials flow**, Salesforce's server-to-server flow
without a user login
([client credentials flow](https://help.salesforce.com/s/articleView?id=sf.remoteaccess_oauth_client_credentials_flow.htm)).
In Setup, create an external client app (or connected app) with the client
credentials flow enabled and the `api` OAuth scope, and pick a **run-as user**:
every job runs with that user's access. The token is requested from
`<My Domain>/services/oauth2/token`.

The run-as user needs *API Enabled*, *View All Data* (or read on each object
and field below) and, for `users`, *View Setup and Configuration*. Fields the
user cannot read make the job fail with `INVALID_FIELD`, which names them.

## Streams

Every stream is one Bulk API 2.0 query job; the SOQL field lists are in the
template. Field definitions:
[Object Reference](https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/).

| Stream | Object | Doc | Operation | Cursor | Primary key |
|---|---|---|---|---|---|
| accounts | `Account` | [Account](https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_account.htm) | `queryAll` | `SystemModstamp` | `Id` |
| contacts | `Contact` | [Contact](https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_contact.htm) | `queryAll` | `SystemModstamp` | `Id` |
| leads | `Lead` | [Lead](https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_lead.htm) | `queryAll` | `SystemModstamp` | `Id` |
| opportunities | `Opportunity` | [Opportunity](https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_opportunity.htm) | `queryAll` | `SystemModstamp` | `Id` |
| opportunity_line_items | `OpportunityLineItem` | [OpportunityLineItem](https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_opportunitylineitem.htm) | `queryAll` | `SystemModstamp` | `Id` |
| users | `User` | [User](https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_user.htm) | `query` | `SystemModstamp` | `Id` |
| campaigns | `Campaign` | [Campaign](https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_campaign.htm) | `queryAll` | `SystemModstamp` | `Id` |
| campaign_members | `CampaignMember` | [CampaignMember](https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_campaignmember.htm) | `queryAll` | `SystemModstamp` | `Id` |
| cases | `Case` | [Case](https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_case.htm) | `queryAll` | `SystemModstamp` | `Id` |
| tasks | `Task` | [Task](https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_task.htm) | `queryAll` | `SystemModstamp` | `Id` |
| events | `Event` | [Event](https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_event.htm) | `queryAll` | `SystemModstamp` | `Id` |

**The job lifecycle.** `POST /jobs/query`
([create a query job](https://developer.salesforce.com/docs/atlas.en-us.api_asynch.meta/api_asynch/query_create_job.htm))
→ poll `GET /jobs/query/{id}` until `state` is `JobComplete` (`Failed` and
`Aborted` fail the stream;
[job info](https://developer.salesforce.com/docs/atlas.en-us.api_asynch.meta/api_asynch/query_get_one_job.htm))
→ `GET /jobs/query/{id}/results?maxRecords=100000`, following the
`Sforce-Locator` response header until it reads `null`
([get results](https://developer.salesforce.com/docs/atlas.en-us.api_asynch.meta/api_asynch/query_get_job_results.htm)).
Results are CSV; Salesforce writes a null as an empty field, which the template
maps back to `null`. Values arrive as text (`"false"`, `"1250000"`), as CSV
carries no types.

**Incremental.** `SystemModstamp` changes on every user or system update and is
indexed, which is why Salesforce recommends it over `LastModifiedDate` for
change detection. After the first full export, each job's SOQL gets
`WHERE SystemModstamp > <bookmark>`. The bookmark is the run's start time minus
a 15-minute lookback, so a record committed while the previous job was running
is read again rather than missed; the upsert on `Id` deduplicates.

**Deletes.** `queryAll` also returns records deleted by a delete or merge that
are still in the Recycle Bin (15 days), with `IsDeleted = true`, and archived
tasks and events (`IsArchived`). Deleting a record updates its
`SystemModstamp`, so a deletion reaches the next incremental run as an upsert
with `IsDeleted` set. Run at least every 15 days, or deletions age out of the
Recycle Bin unseen. `User` has no `IsDeleted` (users are deactivated, `IsActive`)
and uses `query`.

## Rate limits and run time

Bulk API 2.0 query jobs count against the org's daily API request allocation
(each create, poll and result-page request is one call) and share the Bulk API
limits: jobs and their results are kept seven days, and a query job's results
must be read within that window
([Bulk API and Bulk API 2.0 limits](https://developer.salesforce.com/docs/atlas.en-us.salesforce_app_limits_cheatsheet.meta/salesforce_app_limits_cheatsheet/salesforce_app_limits_platform_bulkapi.htm),
[Bulk API 2.0 limits](https://developer.salesforce.com/docs/atlas.en-us.api_asynch.meta/api_asynch/bulk_common_limits.htm)).
A run costs about a dozen calls per object, whatever the row count. Polling
backs off from 1 to 10 seconds; a job may run up to two hours before the
stream gives up. `REQUEST_LIMIT_EXCEEDED` means the daily allocation is spent.

Each job carries a fixed queueing cost of roughly 10–30 seconds, so small
objects take about that long regardless of size; large exports stream at
hundreds of thousands of rows per minute. A first export of 10 million
records usually finishes in 10–30 minutes; incremental runs take about a
minute per object.

## Live smoke test

```bash
faucet run --source faucet-hq/salesforce --sink faucet-hq/jsonl \
  --param salesforce_url=https://<mydomain>.my.salesforce.com \
  --param salesforce_client_id="$SF_CLIENT_ID" --param salesforce_client_secret="$SF_CLIENT_SECRET" \
  --param out_dir=./out
wc -l out/salesforce/*.jsonl
```

Use a sandbox (`https://<mydomain>--<sandbox>.sandbox.my.salesforce.com`)
first.

## Limitations

- **Fixed field lists.** Bulk API 2.0 does not accept `FIELDS(ALL)`, and the
  REST source cannot describe an object first and build its `SELECT`, so each
  stream selects the documented standard fields. Custom fields (`…__c`) need a
  copy of the template with them added. `faucet discover` with a `salesforce:`
  source block generates field-complete queries for one org.
- CSV values are strings; cast in the warehouse or with a `cast` transform.
- Small objects still pay the bulk job's queueing time; the engine's
  `sync_below_rows` routing would need a per-stream synchronous query path that
  this template does not configure yet.

## Changelog

- **v1** — first release, built from the Bulk API 2.0 and Object Reference
  documentation: eleven objects, `queryAll` soft deletes, incremental on
  `SystemModstamp`, client credentials auth, API v67.0.
