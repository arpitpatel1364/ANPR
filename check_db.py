from db_connection import DatabaseConnection

with DatabaseConnection() as db:
    rows = db.fetch_all("DESCRIBE cameras")
    for r in rows:
        print(r)
