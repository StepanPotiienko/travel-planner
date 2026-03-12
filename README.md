# Travel Planner

A management application that helps travellers plan trips and collect desired places to visit.
Built with **Flask**, **SQLite**, and the **Art Institute of Chicago public API**.

## Quick Start (local)

```bash
# 1. Clone the repository
git clone <repo-url>
cd TravelPlanner

# 2. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables
cp .env.example .env
# Edit .env to set SECRET_KEY, ADMIN_USERNAME, ADMIN_PASSWORD as needed

# 5. Run the application
flask run --debug
```

Open [http://localhost:5000](http://localhost:5000) and sign in with your credentials (default: `admin` / `admin`).

---

## Docker

```bash
docker compose up --build
```

The app will be available at [http://localhost:5000](http://localhost:5000).
The SQLite database is persisted in a named Docker volume (`db_data`).

---

## REST API

All API endpoints are under `/api/` and require **HTTP Basic Authentication**.

### Projects

| Method   | Endpoint             | Description                                      |
| -------- | -------------------- | ------------------------------------------------ |
| `POST`   | `/api/projects`      | Create a project (with optional places)          |
| `GET`    | `/api/projects`      | List projects (paginated, filterable)            |
| `GET`    | `/api/projects/<id>` | Get a project with a given id                    |
| `PUT`    | `/api/projects/<id>` | Update project information                       |
| `DELETE` | `/api/projects/<id>` | Delete project (blocked if visited places exist) |

## Finding Artwork IDs

Search the Art Institute of Chicago API directly:

```
https://api.artic.edu/api/v1/artworks/search?q=monet&fields=id,title
```

Use the `id` field as `external_id` when adding a place.
