//! Migration smoke test.
//!
//! Skipped unless `TEST_DATABASE_URL` points at a disposable database. CI
//! provides one via a service container; locally you can point it at a
//! throwaway Postgres. The schema is dropped afterwards so the test is
//! repeatable.

use sqlx::postgres::PgPoolOptions;

#[tokio::test]
async fn migrations_apply_and_seed_once() {
    let Ok(url) = std::env::var("TEST_DATABASE_URL") else {
        eprintln!("TEST_DATABASE_URL not set; skipping migration test");
        return;
    };

    let pool = PgPoolOptions::new()
        .max_connections(1)
        .connect(&url)
        .await
        .expect("connect to test database");

    // Start from a clean slate so reruns behave the same way. The migration
    // ledger lives in `public`, so it must go too.
    for statement in [
        "drop schema if exists core cascade",
        "drop table if exists _sqlx_migrations",
    ] {
        sqlx::query(statement)
            .execute(&pool)
            .await
            .expect("reset test database");
    }

    devicehub_hub::db::migrate(&pool)
        .await
        .expect("first migrate");
    // A second run must be a no-op rather than an error.
    devicehub_hub::db::migrate(&pool)
        .await
        .expect("second migrate");

    let tenants: i64 = sqlx::query_scalar("select count(*) from core.tenant")
        .fetch_one(&pool)
        .await
        .expect("count tenants");
    let devices: i64 = sqlx::query_scalar("select count(*) from core.device")
        .fetch_one(&pool)
        .await
        .expect("count devices");

    assert_eq!(tenants, 1, "seed must be idempotent");
    assert_eq!(devices, 1, "seed must be idempotent");

    for statement in [
        "drop schema core cascade",
        "drop table if exists _sqlx_migrations",
    ] {
        sqlx::query(statement)
            .execute(&pool)
            .await
            .expect("clean up test database");
    }
}
