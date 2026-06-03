# Leave Management Microservices

A microservices-based leave management application demonstrating service discovery, API gateway, JWT security, async messaging, and resilient inter-service communication.

## Architecture

```
                    ┌──────────────────┐
                    │  Spring Gateway  │
                    │   (Port: 8000)   │
                    └────────┬─────────┘
                             │
     ┌───────────┬───────────┼───────────┬──────────────┐
     │           │           │           │              │
┌────▼────┐ ┌────▼────┐ ┌────▼────┐ ┌────▼────┐   ┌─────▼─────┐
│  Auth   │ │Employee │ │  Leave  │ │Notify   │   │  Eureka   │
│ Service │ │ Service │ │ Service │ │Service  │   │  Server   │
│  :8001  │ │  :8002  │ │  :8003  │ │ :8004   │   │   :8761   │
└────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘   └───────────┘
     │           │           │           │
     └───────────┴───────────┘           │
                 │                 ┌─────▼─────┐
                 │                 │ RabbitMQ  │
                 └────────────────►│  :5672    │
                    publish/consume └───────────┘
```

## Services

| Service | Port | Description |
|---------|------|-------------|
| Eureka Server | 8761 | Service registry for dynamic discovery |
| Spring Gateway | 8000 | Public API entry — routing, JWT auth, load balancing |
| Auth Service | 8001 | Login and JWT token issuance |
| Employee Service | 8002 | Employee data, leave balances, manager/report links |
| Leave Service | 8003 | Apply, approve, reject, and history for leave requests |
| Notification Service | 8004 | RabbitMQ consumer for leave notifications + error logging |
| RabbitMQ | 5672 | Async message broker |

## Key Patterns

| Pattern | Module | Implementation |
|---------|--------|----------------|
| Service Discovery | All | Eureka — services register by name, clients resolve by name |
| API Gateway | `spring-gateway` | Single entry point; path-based routing with `lb://` URIs |
| JWT Authentication | `spring-gateway` | `JwtAuthenticationFilter` validates tokens; injects user headers |
| Role-Based Access | Python services | `shared/authorization.py` — employee, manager, admin rules |
| Client-side Load Balancing | Gateway + Python | Round Robin via Spring Cloud LoadBalancer and `eureka_lookup.py` |
| Async Notifications | `leave-service` → RabbitMQ → `notification-service` | Topic exchange `leave.exchange`, queue `notification.queue` |
| Circuit Breaker | `shared/circuit_breaker.py` | `pybreaker` on inter-service HTTP calls |
| Retry with Backoff | `shared/circuit_breaker.py` | `tenacity` — 3 attempts, 500ms base, x2 multiplier |
| Centralized Error Logging | `shared/notification_client.py` | HTTP `POST /notify/error` to notification-service |
| Resilient HTTP Client | Python services | `resilient_request()` — Eureka lookup + retry + circuit breaker |

## Prerequisites

- Docker Desktop (recommended), or
- Java 17+ and Maven (for Eureka + Gateway), Python 3.12+ (for backend services)

## Running the Application

### Docker (recommended)

```bash
docker compose build
docker compose up
```

See [`DOCKER.md`](DOCKER.md) for details.

### Local startup order

1. **Eureka Server**
```bash
cd eureka-server
mvn spring-boot:run
```

2. **Python backend services** (employee → auth → leave → notification)

3. **Spring Gateway**
```bash
cd spring-gateway
mvn spring-boot:run
```

## API Endpoints

All requests go through the gateway at `http://localhost:8000`. Protected routes require `Authorization: Bearer <token>`.

### Auth (via Gateway)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/auth/login` | Login and receive JWT (public) |

### Employee (via Gateway)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/employees` | Create employee (admin) |
| GET | `/employees/{emp_id}/leave-details` | Leave balances and details |

### Leave (via Gateway)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/employees/{emp_id}/apply-leave` | Submit leave request |
| GET | `/employees/{emp_id}/leave-history` | Employee leave history |
| GET | `/employees/{emp_id}/team-leave-requests` | Manager/admin team requests |
| PUT | `/leaves/{leave_id}/approve` | Approve pending leave |
| PUT | `/leaves/{leave_id}/reject` | Reject pending leave |

## Sample API Calls

### Login
```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"john","password":"john123"}'
```

### Apply Leave
```bash
curl -X POST http://localhost:8000/employees/101/apply-leave \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "leave_type": "casual",
    "start_date": "2026-09-01",
    "end_date": "2026-09-01",
    "days": 1,
    "reason": "Personal errand"
  }'
```

### Approve Leave
```bash
curl -X PUT http://localhost:8000/leaves/1/approve \
  -H "Authorization: Bearer <manager_token>"
```

## Async Notification Flow

1. Leave service saves the leave and publishes an event to RabbitMQ (`leave.submitted`, `leave.approved`, or `leave.rejected`).
2. API responds immediately — it does not wait for notification delivery.
3. Notification service consumes from `notification.queue` and logs the message.
4. Audit entries are published to the `leave-logs` queue.

## Eureka Dashboard

Access at: http://localhost:8761

## Initial Data

Employee and leave seed data is loaded from `employee-service/employees.json` and `leave-service/leaves.json`.

### Test users

| Username | Password | Role | Employee ID |
|----------|----------|------|-------------|
| john | john123 | employee | 101 |
| manager_eng | manager123 | manager | 201 |
| admin | admin123 | admin | 301 |

## Swagger UI

Aggregated API docs for all backend services (public, no JWT required):

- **http://localhost:8000/swagger-ui.html**

## Postman Testing

Import [`postman/Leave-Management-Gateway.postman_collection.json`](postman/Leave-Management-Gateway.postman_collection.json) and follow [`POSTMAN-TEST-CASES.md`](POSTMAN-TEST-CASES.md).

## Project Structure

```
├── eureka-server/          # Java — Netflix Eureka
├── spring-gateway/         # Java — Spring Cloud Gateway + JWT
├── auth-service/           # Python FastAPI
├── employee-service/       # Python FastAPI
├── leave-service/          # Python FastAPI
├── notification-service/   # Python FastAPI + RabbitMQ consumer
├── shared/                 # Cross-cutting Python modules
├── docker-compose.yml
├── ARCHITECTURE.md
├── DOCKER.md
└── POSTMAN-TEST-CASES.md
```
