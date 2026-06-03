# Postman Test Guide

Import the collection and run tests against the **Spring Cloud Gateway** at `http://localhost:8000`.

**Collection:** [`postman/Leave-Management-Gateway.postman_collection.json`](postman/Leave-Management-Gateway.postman_collection.json)

## Setup

1. Start the stack: `docker compose up` (see [`DOCKER.md`](DOCKER.md)).
2. Postman → **Import** → select the collection JSON file.
3. Confirm collection variable `baseUrl` = `http://localhost:8000`.
4. Run folder **01 - Login** first — saves `employee_token`, `manager_token`, `admin_token`.
5. Run remaining folders in order, or **Run collection** for automated tests.

Protected requests need:

```http
Authorization: Bearer <access_token>
```

## Gateway endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/auth/login` | No | Get JWT token |
| POST | `/employees` | Admin | Create employee |
| GET | `/employees/{emp_id}/leave-details` | Yes | Leave balances |
| POST | `/employees/{emp_id}/apply-leave` | Yes | Submit leave |
| GET | `/employees/{emp_id}/leave-history` | Yes | Own history |
| GET | `/employees/{emp_id}/team-leave-requests` | Manager/Admin | Team requests |
| PUT | `/leaves/{leave_id}/approve` | Manager/Admin | Approve leave |
| PUT | `/leaves/{leave_id}/reject` | Manager/Admin | Reject leave |

## Test users

| Username | Password | Role | Employee ID |
|----------|----------|------|-------------|
| john | john123 | employee | 101 |
| alice | alice123 | employee | 102 |
| manager_eng | manager123 | manager | 201 |
| admin | admin123 | admin | 301 |

## Collection folders

| Folder | Token used | What it tests |
|--------|------------|---------------|
| 01 - Login | — | Login for employee, manager, admin; create employee |
| 02 - Employee Flow | employee | Leave details, history, apply leave (valid + validation errors) |
| 03 - Manager Flow | manager | Team view, direct reports, forbidden access |
| 04 - Admin Flow | admin | All requests, create employee |
| 05 - Approve/Reject | manager | Approve leave 1, reject leaves 2 and 3 |

## Seed leave data (folder 05)

| leave_id | Employee | Status | Dates |
|----------|----------|--------|-------|
| 1 | john (101) | PENDING | 2026-05-01 → 2026-05-02 |
| 2 | alice (102) | PENDING | 2026-06-10 |
| 3 | john (101) | PENDING | 2026-07-15 → 2026-07-16 |

Use dates **2026-05-01 to 2026-05-02** in apply-leave to trigger an **overlap** error.

## Sample request bodies

### Login
```json
{"username": "john", "password": "john123"}
```

### Apply leave (valid)
```json
{
  "leave_type": "casual",
  "start_date": "2026-09-01",
  "end_date": "2026-09-01",
  "days": 1,
  "reason": "Personal errand"
}
```

### Reject leave (with comments)
```json
{"rejection_comments": "Team coverage insufficient"}
```

## Async notifications

Business notifications (apply/approve/reject) are delivered **asynchronously** via RabbitMQ. The API returns **200/201 immediately**. Verify delivery in notification-service logs:

```
LEAVE NOTIFICATION RECEIVED
```

## Common expected results

| Scenario | Expected status |
|----------|-----------------|
| Valid login | 200 + token |
| Wrong password | 401 |
| Missing token on protected route | 401 |
| Employee views another employee's data | 403 |
| Overlapping leave dates | 400 |
| Insufficient leave balance | 400 |
| Approve already-processed leave | 400 |
| Service not registered in Eureka | 503 |

## Reset test state

If approve/reject tests fail because leaves were already processed:

```bash
docker compose restart leave-service
```

See also: [`ARCHITECTURE.md`](ARCHITECTURE.md), [`DOCKER.md`](DOCKER.md).
