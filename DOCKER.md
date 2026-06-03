# Docker — Leave Management Microservices

Run the full stack with Docker Compose. Postman uses **`http://localhost:8000`** as the gateway base URL.

## Prerequisites

| Requirement | Notes |
|-------------|--------|
| Docker Engine | Docker Desktop on Windows is fine |
| Docker Compose v2 | `docker compose` (built into Docker Desktop) |
| Free host ports | **8761** (Eureka), **8000** (Gateway) |
| RAM | ~2–4 GB for JVM + Python containers |

You do **not** need Java, Maven, or Python installed on the host for normal use.

## Quick start

From the project root:

```bash
docker compose build
docker compose up
```

Detached mode:

```bash
docker compose up -d
```

Stop:

```bash
docker compose down
```

Scale multiple instances (optional):

```bash
docker compose up --scale leave-service=2 --scale employee-service=2
```

## Verify

1. **Eureka dashboard:** http://localhost:8761 — expect **UP** instances for:
   - `SPRING-GATEWAY`
   - `AUTH-SERVICE`
   - `EMPLOYEE-SERVICE`
   - `LEAVE-SERVICE`
   - `NOTIFICATION-SERVICE`

2. **Gateway health:** http://localhost:8000/actuator/health

3. **Swagger UI:** http://localhost:8000/swagger-ui.html (aggregated docs for all services)

4. **Postman:** import [`postman/Leave-Management-Gateway.postman_collection.json`](postman/Leave-Management-Gateway.postman_collection.json), set `baseUrl` to `http://localhost:8000`, run folder **01 - Login** first.

5. **Async notifications:** after apply/approve/reject, check notification-service logs for `LEAVE NOTIFICATION RECEIVED`.

## Compose services

| Compose service | Eureka name | Role |
|-----------------|-------------|------|
| eureka-server | — | Service registry |
| spring-gateway | SPRING-GATEWAY | Public edge — routing, JWT, load balancing |
| auth-service | AUTH-SERVICE | Login |
| employee-service | EMPLOYEE-SERVICE | Employees, balances, leave details |
| leave-service | LEAVE-SERVICE | Leave apply/approve/reject/history |
| notification-service | NOTIFICATION-SERVICE | RabbitMQ consumer + error logging |
| rabbitmq | — | Message broker |

## Startup order

1. `eureka-server` + `rabbitmq` (healthy)
2. `employee-service`, `notification-service`
3. `auth-service`, `leave-service`
4. `spring-gateway` (public entry on port 8000)

First startup may take 2–3 minutes while Maven builds Eureka and Spring Gateway images.

## Environment variables

| Variable | Default | Used by | Purpose |
|----------|---------|---------|---------|
| `PORT` | service default | Python services | Uvicorn listen port |
| `SERVICE_HOST` | service name | Python services | Eureka instance hostname |
| `EUREKA_SERVER` | `http://eureka-server:8761/eureka` | All services | Registry URL |
| `RABBITMQ_HOST` | `rabbitmq` | leave-service, notification-service | Broker hostname |
| `RABBITMQ_PORT` | `5672` | leave-service, notification-service | Broker port |
| `RABBITMQ_USERNAME` | `guest` | leave-service, notification-service | Broker username |
| `RABBITMQ_PASSWORD` | `guest` | leave-service, notification-service | Broker password |
| `RABBITMQ_QUEUE` | `leave-logs` | notification-service | Audit queue name |
| `HTTP_RETRY_MAX_ATTEMPTS` | `3` | Python services | HTTP retry attempts |
| `HTTP_RETRY_BASE_WAIT_MS` | `500` | Python services | Initial retry wait |
| `HTTP_RETRY_MULTIPLIER` | `2` | Python services | Exponential backoff multiplier |

## Reset in-memory data

Leave and employee JSON are baked into the image (not persisted to volumes):

```bash
docker compose restart leave-service employee-service
```

Full rebuild after code changes:

```bash
docker compose build --no-cache
docker compose up
```

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Gateway **503** | Service not in Eureka | Wait for healthchecks; open http://localhost:8761 |
| No notification logs | RabbitMQ or consumer not ready | Check `docker compose logs notification-service` |
| Leave succeeds but no notification | notification-service down | Event queued in RabbitMQ; delivered when consumer restarts |
| Postman approve/reject fails | Leave already processed | `docker compose restart leave-service` |
| Port already in use | Local dev still running | Stop local services or change compose ports |
| Eureka build fails | Maven/network issue | `docker compose build eureka-server --no-cache` |

## Files

| File | Role |
|------|------|
| [`docker-compose.yml`](docker-compose.yml) | Full stack definition |
| [`eureka-server/Dockerfile`](eureka-server/Dockerfile) | Java 17 Eureka (Maven build) |
| [`spring-gateway/Dockerfile`](spring-gateway/Dockerfile) | Java 17 Spring Cloud Gateway |
| `*/Dockerfile` | One image per Python service |
| [`.dockerignore`](.dockerignore) | Smaller build context |

See also: [`ARCHITECTURE.md`](ARCHITECTURE.md), [`POSTMAN-TEST-CASES.md`](POSTMAN-TEST-CASES.md).
