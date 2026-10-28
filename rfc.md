# Notification Service

## Overview
We will build a service that sends email and SMS notifications to our customers when their orders change status. Other services call it through a REST API.

## Architecture
The Notification API validates each request, stores it in a single PostgreSQL instance, and sends the message immediately in the same request by calling the email and SMS providers. There is one instance of the API behind no load balancer.

## Data
All notifications are stored in one table with a JSON column for the message body. Customer phone numbers and email addresses are stored in plain text. There are no indexes other than the primary key. Records are never deleted.

## Security
Services authenticate to the API with a shared API key that is the same for every service and never changes. The API has no rate limit.

## Scalability
We expect traffic to grow ten times during the holiday sale. We will handle this by adding more memory to the server if it becomes slow.

## Reliability
If a provider call fails, the request returns an error and the caller must try again. There are no retries, no queue, and no alerts. We do not take backups of the database.

## Open questions
How we handle customers who opted out of SMS is not yet decided.