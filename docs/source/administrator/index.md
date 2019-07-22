Title: Administrator

# Administration Tools

This section contains information relevant to system administrators. This includes setting up [FlowAuth](#granting-user-permissions-in-flowauth) to allow users to generate FlowAPI access tokens, and managing the [cache](#caching-in-flowkit) and [log files](#logging-and-audit-trails).

## Granting user permissions in FlowAuth

FlowAuth is the tool which analysts will use to generate tokens which will allow them to communicate with a FlowKit server through FlowAPI. The following steps using the FlowAuth administration tool are required to add a user and allow them to generate access tokens:

1. Log into FlowAuth as an administrator.

2. Under "API Routes", add any applicable API routes (e.g. `daily_location`).

3. Under "Aggregation Units", add any applicable aggregation units (e.g. `admin3`).

3. Under "Servers", add a new server and give it a name. Note that the name must match the `FLOWAPI_IDENTIFIER` variable set in the FlowAPI docker container on this server.

4. Enable any permissions for this server under "API Permissions", and aggregation units under "Aggregation Units".

5. Under "Users", add a new user, and set the username and password.

6. Either:
    - Add a server to the user, and enable/disable API permissions and aggregation units,
    <p>
7. Or:
    <p>
    - Under "Groups", add a new group,

    - Add a server to the group, and enable/disable API permissions and aggregation units,

    - Add the user to the group.

The user can then log into FlowAuth and generate a token (see the [analyst section](../analyst/index.md#flowauth) for instructions).

## Caching in FlowKit

FlowKit implements a caching system to enhance performance. Queries requested via FlowAPI are cached in FlowDB, under the `cache` schema.

Once cached, a query will not be recalulated - the cached version will simply be returned instead, which can save significant computation time. In addition to queries which are _directly_ returned, FlowKit may cache queries which are used in calculating other queries. For example, calculating a modal location aggregate, and a daily location aggregate will both use the same underlying query when the dates (and other parameters) overlap. Hence, caching the underlying query allows both the aggregate and the modal location aggregate to be produced faster.

This performance boost is achieved at the cost of disk space usage. Flowmachine automatically manages the size of the on-disk cache, and will remove seldom used cache entries periodically. The frequency of this check can be configured using the `FLOWMACHINE_CACHE_PRUNING_FREQUENCY` environment variable. By default, this is set to `86400`, or 24 hours in seconds. For heavily used servers, it may be desirable to set this to a lower threshold. Automatic cache clearance follows the procedure described in the following section. 

When a query is requested via the API, the query itself will be cached along with all of the other queries on which its calculation depends. For complex queries this can result in a large number of tables being added to the cache. This default behaviour can be changed by setting the environment variable `FLOWMACHINE_SERVER_DISABLE_DEPENDENCY_CACHING=true` when starting the FlowMachine server, which will result in only the specific queries requested being cached. Computation times may be significantly longer when dependency caching is turned off.

### Cache Management

FlowMachine and FlowDB provide tools to inspect and manage the content of FlowKit's cache. FlowDB also contains metadata about the content of cache, in the `cache.cached` table.

Administrators can inspect this table directly by connecting to FlowDB, but in many scenarios the better option is to make use of FlowMachine's [cache management module](../flowmachine/flowmachine/core/cache/).

The cache submodule provides functions to assess the disk usage of the cache tables, and to reduce the disk usage below a desired threshold.

#### Shrinking Cache

To identify which tables should be discarded from cache, FlowKit keeps track of how expensive they were to calculate initially, how much disk space they occupy, and how often and recently they have been used. These factors are combined into a cache score, based on the [cachey](https://github.com/dask/cachey) algorithm.

Each cache table has a cache score, with a higher score indicating that the table has more cache value.

FlowMachine provides two functions which make use of this cache score to reduce the size of the cache - [`shrink_below_size`](../flowmachine/flowmachine/core/cache/#shrink_below_size), and [`shrink_one`](../flowmachine/flowmachine/core/cache/#shrink_one). `shrink_one` flushes the table with the _lowest_ cache score. `shrink_below_size` flushes tables until the disk space used by the cache falls below a threshold[^1] by calling `shrink_one` repeatedly. By default, queries which have been recently calculated are *excluded* from removal. To configure the global default for the exclusion period, set the `CACHE_PROTECTED_PERIOD` environment variable for FlowDB, or update the `cache_protected_period` key in the `cache.cache_config` table. The default exclusion period is `86400`s (24 hours). This can also be overridden when calling the cache management functions directly.

If necessary, the cache can also be completely reset using the [`reset_cache`](../flowmachine/flowmachine/core/cache/#reset_cache) function.

#### Removing a Specific Query from Cache

If a specific query must be removed from the cache, then an administrator can use the [`invalidate_cache_by_id`](../flowmachine/flowmachine/core/cache/#invalidate_cache_by_id) function of the `cache` submodule.

By default, this function only removes that specific query from cache. However, setting the `cascade` argument to `True` will also flush from the cache any cached queries which used that query in their calculation. This will also cascade to any queries which used _those_ queries, and so on.

#### Configuring the Cache

There are three parameters which control FlowKit's cache, both of which are in the `cache.cache_config` table. `half_life` controls how much weight is given to recency of access when updating the cache score. `half_life` is in units of number of cache retrievals, so a larger value for `half_life` will give less weight to recency and frequency of access. 

!!! example
    `big_query` and `small_query` both took 100 seconds to calculate. `big_query` takes 100 bytes to store, and `small_query` takes 10 bytes.
    Their _costs_ are `compute_time/storage_size`, or 1 for `big_query` and 10 for `small_query`. `small_query` is stored first and has an initial cache score of 10.
    If query `big_query` is stored next, with a `half_life` of 2.0, it will get an initial cache score of 1.35. 
    
    Just in terms of the balance between compute time and storage cost, `small_query` is more valuable in cache because it is relatively cheaper to store.  However, after only four retrievals of `big_query` from cache, `big_query` will have a cache score of 13.3, meaning it is more valuable in cache because it is so frequently used.
    
    If `half_life` was instead set to 10.0, `big_query` would need to be retrieved _seven_ times to exceed the cache score of `small_query`. 
     
 
`cache_size` is the maximum size in bytes that the cache tables should occupy on disk. These settings default to 1000.0, and 10% of available space on the drive where `/var/lib/postgresql/data` is located.

`cache_protected_period` is the length of time in seconds that a cache table is, by default, immune from being removed by a cache shrinkage operation. This defaults to `86400`s, or 24 hours. During this time, cache tables will not be removed by automatic cache shrinking, and will be default be excluded from the cache management functions.

These values can be overridden when creating a new FlowDB container by setting the `CACHE_SIZE`, `CACHE_HALF_LIFE` and  `CACHE_PROTECTED_PERIOD` environment variables for the container, set by updating the `cache.cache_config` table after connecting directly to FlowDB, or modified using the cache submodule.

#### Redis and the Query Cache

FlowMachine also tracks the execution state of queries using redis. In some cases, it is possible for redis and the cache metadata table to get out of sync with one another (for example, if either redis or FlowDB has been manually edited). To deal with this, you can forcibly resync redis with FlowDB's cache table, using the `resync_redis_with_cache` function. This will reset redis, and repopulate it based _only_ on the contents of `cache.cached`.

!!! warning
    You _must_ ensure that no queries are currently running before using this function. Any queries that are currently running will become out of sync.    

[^1]:By default, this uses the value set for `cache_size` in `cache.cache_config`.

## Logging and Audit Trails

FlowKit supports structured logging in JSON form throughout FlowMachine and FlowAPI. By default both FlowMachine and FlowAPI will only log errors, and audit logs.

Audit trail logs are _always_ written to stdout. Error and debugging logs are, by default, only written to stderr. 

### Audit Trail Logs

Three kinds of access log are written on each request handled by FlowAPI: authentication, data access at API side, and data access on the FlowMachine side.


#### Authentication Logs

FlowAPI logs all access attempts whether successful or not to stdout using a logger named `flowapi.access`.

Where authentication succeeds, the log message will have a `level` field of `info`, and an `event` type of `AUTHENTICATED`:

```json
{
	"request_id": "fe1d5dd2-ddfb-4b34-9d1e-4ebfc205d64c",
	"route": "/api/0/run",
	"user": "TEST_USER",
	"src_ip": "127.0.0.1",
	"json_payload": {
		"params": {
			"date": "2016-01-01",
			"level": "admin3",
			"method": "last",
			"aggregation_unit": "admin3",
			"subscriber_subset": "all"
		},
		"query_kind": "daily_location"
	},
	"event": "AUTHENTICATED",
	"logger": "flowapi.access",
	"level": "info",
	"timestamp": "2019-01-10T13:57:35.262214Z"
}
```

In general, access log messages contain at a minimum the route that access was requested to, any json payload, source IP address for the request, and a timestamp. Every request _also_ has a _unique id_, which will be the same across all log entries related to that request.

If authentication fails, then the reason is also included in the log message, along with any error message and as much information about the request and requester as can be discerned.

#### API Usage Logs

After a request is successfully authenticated (has a valid token), the _nature_ of the request will be logged at several points. When the request is received, if at any point the request is rejected because the provided token did not grant access, and when the request is fulfilled.

As with the authentication log, the usage log is written to stdout using a logger named `flowapi.query`.

#### FlowMachine Usage Logs

If a request has triggered an action in the FlowMachine backend, logs will also be written there. These logs will include the `request_id` for the API request which originally triggered them.

As with the FlowAPI loggers, these messages are written to stdout, using the `flowmachine.query_run_log` logger.

#### Complete Logging Cycle

A complete logging cycle for a successful request to retrieve a previously run query's results might look like this:

FlowAPI access log:

```json
{
	"request_id": "d2892489-8fb8-40ec-94e6-2467266a0226",
	"route": "/api/0/get/ddc61a04f608dee16fff0655f91c2057",
	"user": "TEST_USER",
	"src_ip": "127.0.0.1",
	"json_payload": null,
	"event": "AUTHENTICATED",
	"logger": "flowapi.access",
	"level": "info",
	"timestamp": "2019-01-10T14:11:03.331967Z"
}
```

FlowAPI usage log:

```json
{
	"request_id": "d2892489-8fb8-40ec-94e6-2467266a0226",
	"query_kind": "DAILY_LOCATION",
	"route": "/api/0/get/ddc61a04f608dee16fff0655f91c2057",
	"user": "TEST_USER",
	"src_ip": "127.0.0.1",
	"json_payload": null,
	"query_id": "ddc61a04f608dee16fff0655f91c2057",
	"claims": {
		"permissions": { "get_result": true, "poll": true, "run": true },
		"spatial_aggregation": [
			"admin2",
			"admin0",
			"admin3",
			"admin1",
			"cell",
			"site"
		]
	},
	"event": "Received",
	"logger": "flowapi.query",
	"level": "info",
	"timestamp": "2019-01-10T14:11:03.337052Z"
}

{
	"request_id": "d2892489-8fb8-40ec-94e6-2467266a0226",
	"query_kind": "DAILY_LOCATION",
	"route": "/api/0/get/ddc61a04f608dee16fff0655f91c2057",
	"user": "TEST_USER",
	"src_ip": "127.0.0.1",
	"json_payload": null,
	"query_id": "ddc61a04f608dee16fff0655f91c2057",
	"claims": {
		"permissions": { "get_result": true, "poll": true, "run": true },
		"spatial_aggregation": [
			"admin2",
			"admin0",
			"admin3",
			"admin1",
			"cell",
			"site"
		]
	},
	"event": "Authorised",
	"logger": "flowapi.query",
	"level": "info",
	"timestamp": "2019-01-10T14:11:03.341010Z"
}
```

FlowMachine usage log:

```json
{
	"query_id": "ddc61a04f608dee16fff0655f91c2057",
	"query_kind": "daily_location",
	"message": "b'{\"request_id\":\"d2892489-8fb8-40ec-94e6-2467266a0226\",\"action\":\"get_query_kind\",\"query_id\":\"ddc61a04f608dee16fff0655f91c2057\"}'",
	"request_id": "d2892489-8fb8-40ec-94e6-2467266a0226",
	"params": { "query_id": "ddc61a04f608dee16fff0655f91c2057" },
	"event": "get_query_kind",
	"logger": "flowmachine.query_run_log",
	"level": "info",
	"timestamp": "2019-01-10T14:11:03.335437Z"
}

{
	"query_id": "ddc61a04f608dee16fff0655f91c2057",
	"retrieved_params": {
		"aggregation_unit": "admin3",
		"method": "last",
		"date": "2016-01-01",
		"level": "admin3",
		"subscriber_subset": "all"
	},
	"message": "b'{\"request_id\":\"d2892489-8fb8-40ec-94e6-2467266a0226\",\"action\":\"get_params\",\"query_id\":\"ddc61a04f608dee16fff0655f91c2057\"}'",
	"request_id": "d2892489-8fb8-40ec-94e6-2467266a0226",
	"params": { "query_id": "ddc61a04f608dee16fff0655f91c2057" },
	"event": "get_params",
	"logger": "flowmachine.query_run_log",
	"level": "info",
	"timestamp": "2019-01-10T14:11:03.339602Z"
}

{
	"query_id": "ddc61a04f608dee16fff0655f91c2057",
	"message": "b'{\"request_id\":\"d2892489-8fb8-40ec-94e6-2467266a0226\",\"action\":\"get_sql\",\"query_id\":\"ddc61a04f608dee16fff0655f91c2057\"}'",
	"request_id": "d2892489-8fb8-40ec-94e6-2467266a0226",
	"params": { "query_id": "ddc61a04f608dee16fff0655f91c2057" },
	"event": "get_sql",
	"logger": "flowmachine.query_run_log",
	"level": "info",
	"timestamp": "2019-01-10T14:11:03.358644Z"
}
```

Note that the `request_id` field is identical across the five log entries, which lets you match the request across the multiple services.

### Error and Debugging Logs

FlowMachine and FlowAPI write logs to stderr. By default, the logging level is `error`. For more verbose logging, set the `FLOWMACHINE_LOG_LEVEL` and/or `FLOWAPI_LOG_LEVEL` environment variables to `info` or `debug` when starting the docker container(s).

Log messages from FlowMachine will show the `logger` field of the log entry as `flowmachine.debug`, and the Python module that emitted the log entry in the `submodule` field (e.g. `{'logger':'flowmachine.debug', 'submodule':'flowmachine.core.query'}`. FlowAPI debugging messages set `logger` to `flowapi.debug`.

### Managing and Monitoring Logs

Because FlowKit employs structured logging, and all log messages are JSON objects, the access and usage logs are easy to use with tools like [Logstash](https://www.elastic.co/products/logstash).

[Filebeat](https://www.elastic.co/docker-kubernetes-container-monitoring) allows you to integrate the logs from stdout and stderr directly into your monitoring system.