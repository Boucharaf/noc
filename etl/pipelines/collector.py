import psycopg2


def load_active_nodes(dsn: str) -> list[dict]:
    """Active nodes with everything the collectors need to map a
    supervision-tool host reference back onto a dim_node code."""
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT code, name, host(ip_address), source_tool, itop_ci_id"
                " FROM dim_node WHERE is_active = TRUE"
            )
            return [
                {
                    "code": code,
                    "name": name,
                    "ip_address": ip,
                    "source_tool": tool,
                    "itop_ci_id": ci_id,
                }
                for code, name, ip, tool, ci_id in cur.fetchall()
            ]
    finally:
        conn.close()
