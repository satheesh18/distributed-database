Checkout the pdf for context
We need to implement a distributed database and implement some algorithms mentioned in the pdf. Planning to implement only 

Timestamp as a Service - Instead of having one timestamp server for the whole system, they use several. That way, no single failure point, and timestamps still stay globally ordered

Cabinet: Dynamically Weighted Consensus - Instead of fixed quorums, this one lets you weigh replicas based on how fast and reliable they are. You do not have to wait for slow nodes if enough good ones respond.

SEER: Performance-Aware Leader Election - We use the same perf we calculate for Cabinet to pick the best leader and When it is time to elect a new leader, this one uses latency predictions to pick the fastest node, instead of choosing randomly or by ID.


We need to give only one endpoint to user, they send MYSQL queries to our logical layer, where we should have all these algorithms implemented.

3 mysql containers(1 master 2 replicas)
1 main container where we have fastapi + python running and it receives the request and it controls everything - coordinating with all the containers
1 container which collects metrics of all mysql containers
1 container for cabinet algo(get metrics from metrics container)
1 container for seer algo(get metrics from metrics container)
2 containers for timestamp algo

This is for a project, so I want minimal implementation that works and readable code with comments.
Btw we decide who is the master and we handle the replication intead of binlog(You would understand after reading the pdf). 't 


Don't write any md files other than readme.md
One docker compose to run all containers
Also just put everything inside backend folder for now
We will decide if we need frontend later(not required for now)

