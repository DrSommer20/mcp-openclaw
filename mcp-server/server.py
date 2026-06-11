import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from mcp.server.fastmcp import FastMCP

# Initialisierung von FastMCP mit Host-Konfiguration
mcp = FastMCP("toy-store-mcp", host="0.0.0.0", port=8000)

# Datenbankverbindung herstellen
def get_db_connection():
    return psycopg2.connect(
        os.environ.get("DATABASE_URL"),
        cursor_factory=RealDictCursor
    )

# --- MCP TOOLS ---

@mcp.tool()
async def get_order_details(order_id: int) -> str:
    """Gibt die Details einer spezifischen Bestellung inklusive gekaufter Produkte zurück."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT o.order_id, o.created_at, o.price_usd, o.items_purchased,
                       oi.product_id, p.product_name
                FROM orders o
                JOIN order_items oi ON o.order_id = oi.order_id
                JOIN products p ON oi.product_id = p.product_id
                WHERE o.order_id = %s
            """, (order_id,))
            result = cur.fetchall()
            return json.dumps(result, default=str) if result else "Keine Bestellung gefunden."
    finally:
        conn.close()

@mcp.tool()
async def analyze_campaign_traffic(utm_campaign: str) -> str:
    """Analysiert Website-Sessions für eine spezifische Marketing-Kampagne nach Gerätetyp."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT device_type, COUNT(*) as session_count
                FROM website_sessions
                WHERE utm_campaign = %s
                GROUP BY device_type
            """, (utm_campaign,))
            result = cur.fetchall()
            return json.dumps(result) if result else "Keine Daten zur Kampagne gefunden."
    finally:
        conn.close()

@mcp.tool()
async def check_refund_status(order_id: int) -> str:
    """Prüft, ob und in welcher Höhe für eine Bestellung Erstattungen vorliegen."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT refund_amount_usd, created_at
                FROM order_item_refunds
                WHERE order_id = %s
            """, (order_id,))
            result = cur.fetchall()
            return json.dumps(result, default=str) if result else "Keine Erstattungen für diese Bestellung."
    finally:
        conn.close()

@mcp.tool()
async def get_top_products(limit: int = 10, date_from: str = None, date_to: str = None) -> str:
    """Gibt die meistverkauften Produkte zurück, optional gefiltert nach Zeitraum (date_from/date_to im Format YYYY-MM-DD)."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            query = """
                SELECT p.product_name, COUNT(oi.product_id) as units_sold,
                       SUM(o.price_usd) as total_revenue_usd
                FROM order_items oi
                JOIN products p ON oi.product_id = p.product_id
                JOIN orders o ON oi.order_id = o.order_id
                WHERE 1=1
            """
            params = []
            if date_from:
                query += " AND o.created_at >= %s"
                params.append(date_from)
            if date_to:
                query += " AND o.created_at <= %s"
                params.append(date_to)
            query += " GROUP BY p.product_name ORDER BY units_sold DESC LIMIT %s"
            params.append(limit)
            cur.execute(query, params)
            result = cur.fetchall()
            return json.dumps(result, default=str) if result else "Keine Daten gefunden."
    finally:
        conn.close()

@mcp.tool()
async def get_revenue_by_month(year: int) -> str:
    """Gibt den monatlichen Umsatzverlauf für ein bestimmtes Jahr zurück."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT TO_CHAR(created_at, 'MM') as month,
                       TO_CHAR(created_at, 'Month') as month_name,
                       COUNT(*) as order_count,
                       SUM(price_usd) as total_revenue_usd,
                       ROUND(AVG(price_usd)::numeric, 2) as avg_order_value_usd
                FROM orders
                WHERE EXTRACT(YEAR FROM created_at) = %s
                GROUP BY TO_CHAR(created_at, 'MM'), TO_CHAR(created_at, 'Month')
                ORDER BY month
            """, (year,))
            result = cur.fetchall()
            return json.dumps(result, default=str) if result else f"Keine Daten für {year}."
    finally:
        conn.close()

@mcp.tool()
async def get_revenue_by_product() -> str:
    """Gibt den Umsatz gruppiert nach Produkt zurück."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT p.product_name,
                       COUNT(oi.product_id) as units_sold,
                       SUM(oi.price_usd) as total_revenue_usd,
                       ROUND(AVG(oi.price_usd)::numeric, 2) as avg_item_price_usd
                FROM order_items oi
                JOIN products p ON oi.product_id = p.product_id
                GROUP BY p.product_name
                ORDER BY total_revenue_usd DESC
            """)
            result = cur.fetchall()
            return json.dumps(result, default=str) if result else "Keine Daten gefunden."
    finally:
        conn.close()

@mcp.tool()
async def get_conversion_rate_by_source() -> str:
    """Analysiert die Conversion-Rate nach Traffic-Quelle (utm_source): Sessions vs. tatsächliche Käufe."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    ws.utm_source,
                    COUNT(DISTINCT ws.website_session_id) as total_sessions,
                    COUNT(DISTINCT o.order_id) as total_orders,
                    ROUND(
                        COUNT(DISTINCT o.order_id)::numeric /
                        NULLIF(COUNT(DISTINCT ws.website_session_id), 0) * 100, 2
                    ) as conversion_rate_pct
                FROM website_sessions ws
                LEFT JOIN orders o ON ws.website_session_id = o.website_session_id
                GROUP BY ws.utm_source
                ORDER BY conversion_rate_pct DESC
            """)
            result = cur.fetchall()
            return json.dumps(result, default=str) if result else "Keine Daten gefunden."
    finally:
        conn.close()

@mcp.tool()
async def get_device_conversion_rate() -> str:
    """Vergleicht Conversion-Rates zwischen verschiedenen Gerätetypen (Mobile, Desktop, Tablet)."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    ws.device_type,
                    COUNT(DISTINCT ws.website_session_id) as total_sessions,
                    COUNT(DISTINCT o.order_id) as total_orders,
                    ROUND(
                        COUNT(DISTINCT o.order_id)::numeric /
                        NULLIF(COUNT(DISTINCT ws.website_session_id), 0) * 100, 2
                    ) as conversion_rate_pct
                FROM website_sessions ws
                LEFT JOIN orders o ON ws.website_session_id = o.website_session_id
                GROUP BY ws.device_type
                ORDER BY conversion_rate_pct DESC
            """)
            result = cur.fetchall()
            return json.dumps(result, default=str) if result else "Keine Daten gefunden."
    finally:
        conn.close()

@mcp.tool()
async def get_refund_rate_by_product(limit: int = 10) -> str:
    """Gibt die Produkte mit den höchsten Retourenquoten zurück."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    p.product_name,
                    COUNT(DISTINCT oi.order_id) as total_orders,
                    COUNT(DISTINCT r.order_id) as refunded_orders,
                    ROUND(
                        COUNT(DISTINCT r.order_id)::numeric /
                        NULLIF(COUNT(DISTINCT oi.order_id), 0) * 100, 2
                    ) as refund_rate_pct,
                    SUM(r.refund_amount_usd) as total_refunded_usd
                FROM order_items oi
                JOIN products p ON oi.product_id = p.product_id
                LEFT JOIN order_item_refunds r ON oi.order_id = r.order_id
                GROUP BY p.product_name
                ORDER BY refund_rate_pct DESC
                LIMIT %s
            """, (limit,))
            result = cur.fetchall()
            return json.dumps(result, default=str) if result else "Keine Daten gefunden."
    finally:
        conn.close()

@mcp.tool()
async def get_repeat_purchase_rate() -> str:
    """Berechnet den Anteil der Kunden, die mehr als einmal bestellt haben."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                WITH customer_orders AS (
                    SELECT user_id, COUNT(*) as order_count
                    FROM orders
                    GROUP BY user_id
                )
                SELECT
                    COUNT(*) as total_customers,
                    SUM(CASE WHEN order_count > 1 THEN 1 ELSE 0 END) as repeat_customers,
                    ROUND(
                        SUM(CASE WHEN order_count > 1 THEN 1 ELSE 0 END)::numeric /
                        NULLIF(COUNT(*), 0) * 100, 2
                    ) as repeat_purchase_rate_pct
                FROM customer_orders
            """)
            result = cur.fetchall()
            return json.dumps(result, default=str) if result else "Keine Daten gefunden."
    finally:
        conn.close()

@mcp.tool()
async def generate_period_report(date_from: str, date_to: str) -> str:
    """
    Erstellt einen vollständigen Geschäftsbericht für einen beliebigen Zeitraum.
    date_from und date_to im Format YYYY-MM-DD, z.B. '2014-01-01' bis '2014-12-31'.
    Enthält Umsatz, Top-Produkte, Conversion-Rate nach Quelle und Erstattungen.
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Umsatz im Zeitraum
            cur.execute("""
                SELECT COUNT(*) as order_count,
                       SUM(price_usd) as revenue_usd,
                       ROUND(AVG(price_usd)::numeric, 2) as avg_order_value_usd
                FROM orders
                WHERE created_at BETWEEN %s AND %s
            """, (date_from, date_to))
            revenue = cur.fetchone()

            # Top 5 Produkte
            cur.execute("""
                SELECT p.product_name, COUNT(*) as units_sold,
                       SUM(oi.price_usd) as revenue_usd
                FROM order_items oi
                JOIN products p ON oi.product_id = p.product_id
                JOIN orders o ON oi.order_id = o.order_id
                WHERE o.created_at BETWEEN %s AND %s
                GROUP BY p.product_name
                ORDER BY units_sold DESC
                LIMIT 5
            """, (date_from, date_to))
            top_products = cur.fetchall()

            # Conversion Rate nach Quelle
            cur.execute("""
                SELECT ws.utm_source,
                       COUNT(DISTINCT ws.website_session_id) as sessions,
                       COUNT(DISTINCT o.order_id) as orders,
                       ROUND(COUNT(DISTINCT o.order_id)::numeric /
                           NULLIF(COUNT(DISTINCT ws.website_session_id), 0) * 100, 2
                       ) as conversion_rate_pct
                FROM website_sessions ws
                LEFT JOIN orders o ON ws.website_session_id = o.website_session_id
                WHERE ws.created_at BETWEEN %s AND %s
                GROUP BY ws.utm_source
                ORDER BY conversion_rate_pct DESC
            """, (date_from, date_to))
            conversion = cur.fetchall()

            # Erstattungen
            cur.execute("""
                SELECT COUNT(*) as refund_count,
                       SUM(refund_amount_usd) as total_refunded_usd
                FROM order_item_refunds
                WHERE created_at BETWEEN %s AND %s
            """, (date_from, date_to))
            refunds = cur.fetchone()

            report = {
                "zeitraum": f"{date_from} bis {date_to}",
                "umsatz": dict(revenue) if revenue else {},
                "top_produkte": [dict(r) for r in top_products],
                "conversion_nach_quelle": [dict(r) for r in conversion],
                "erstattungen": dict(refunds) if refunds else {}
            }
            return json.dumps(report, default=str)
    finally:
        conn.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(mcp.sse_app(), host="0.0.0.0", port=8000)
