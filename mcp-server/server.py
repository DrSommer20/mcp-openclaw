import os
import json
import logging
import decimal
import datetime
import traceback
import psycopg2
from psycopg2.extras import RealDictCursor
from pydantic import Field
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Logging-Konfiguration
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("toy-store-mcp")

# ---------------------------------------------------------------------------
# JSON-Encoder: serialisiert Decimal und datetime sauber
# ---------------------------------------------------------------------------
class SafeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, decimal.Decimal):
            return float(obj)
        if isinstance(obj, (datetime.datetime, datetime.date)):
            return obj.isoformat()
        return super().default(obj)

def to_json(data) -> str:
    return json.dumps(data, cls=SafeEncoder)

# ---------------------------------------------------------------------------
# Datenbankverbindung
# ---------------------------------------------------------------------------
def get_db_connection():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise EnvironmentError("Umgebungsvariable DATABASE_URL ist nicht gesetzt.")
    logger.debug("Öffne DB-Verbindung …")
    return psycopg2.connect(db_url, cursor_factory=RealDictCursor)

# ---------------------------------------------------------------------------
# Hilfsfunktion: Query ausführen und Ergebnis zurückgeben
# ---------------------------------------------------------------------------
def _fetch_all(conn, query: str, params=None):
    with conn.cursor() as cur:
        cur.execute(query, params or ())
        return cur.fetchall()

def _fetch_one(conn, query: str, params=None):
    with conn.cursor() as cur:
        cur.execute(query, params or ())
        return cur.fetchone()

# ---------------------------------------------------------------------------
# FastMCP-Initialisierung
# ---------------------------------------------------------------------------
mcp = FastMCP(
    "toy-store-mcp",
    instructions="MCP-Server fuer einen fiktiven Toy Store. Verfuegbarer Datensatz: 2012-03-19 bis 2015-03-19. Anfragen ausserhalb dieses Zeitraums liefern keine Ergebnisse.",
    host="0.0.0.0",
    port=8000
)

# ---------------------------------------------------------------------------
# MCP TOOLS
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_order_details(
    order_id: int = Field(..., description="Die numerische ID der Bestellung"),
) -> str:
    """Gibt die Details einer spezifischen Bestellung inklusive gekaufter Produkte zurück."""
    logger.info("get_order_details aufgerufen | order_id=%s", order_id)
    conn = get_db_connection()
    try:
        result = _fetch_all(conn, """
            SELECT o.order_id, o.created_at, o.price_usd, o.items_purchased,
                   oi.product_id, p.product_name
            FROM orders o
            JOIN order_items oi ON o.order_id = oi.order_id
            JOIN products p    ON oi.product_id = p.product_id
            WHERE o.order_id = %s
        """, (order_id,))
        logger.info("get_order_details | %d Zeilen zurückgegeben", len(result))
        return to_json(result) if result else "Keine Bestellung gefunden."
    except Exception:
        logger.error("Fehler in get_order_details:\n%s", traceback.format_exc())
        raise
    finally:
        conn.close()


@mcp.tool()
async def analyze_campaign_traffic(
    utm_campaign: str = Field(..., description="Name der UTM-Kampagne, z.B. 'spring_sale_2014'"),
    date_from: str = Field(None, description="Startdatum YYYY-MM-DD, optional"),
    date_to: str = Field(None, description="Enddatum YYYY-MM-DD, optional"),
) -> str:
    """Analysiert Website-Sessions fuer eine spezifische Marketing-Kampagne nach Geraetetyp. Optional filterbar nach Zeitraum (Datensatz: 2012-03-19 bis 2015-03-19)."""
    logger.info("analyze_campaign_traffic aufgerufen | utm_campaign=%s date_from=%s date_to=%s", utm_campaign, date_from, date_to)
    conn = get_db_connection()
    try:
        query = """
            SELECT device_type, COUNT(*) as session_count
            FROM website_sessions
            WHERE utm_campaign = %s
        """
        params = [utm_campaign]
        if date_from:
            query += " AND created_at >= %s"
            params.append(date_from)
        if date_to:
            query += " AND created_at <= %s"
            params.append(date_to)
        query += " GROUP BY device_type"
        result = _fetch_all(conn, query, params)
        logger.info("analyze_campaign_traffic | %d Zeilen zurueckgegeben", len(result))
        return to_json(result) if result else "Keine Daten zur Kampagne gefunden."
    except Exception:
        logger.error("Fehler in analyze_campaign_traffic:\n%s", traceback.format_exc())
        raise
    finally:
        conn.close()


@mcp.tool()
async def check_refund_status(
    order_id: int = Field(..., description="Die numerische ID der Bestellung"),
) -> str:
    """Prüft, ob und in welcher Höhe für eine Bestellung Erstattungen vorliegen."""
    logger.info("check_refund_status aufgerufen | order_id=%s", order_id)
    conn = get_db_connection()
    try:
        result = _fetch_all(conn, """
            SELECT refund_amount_usd, created_at
            FROM order_item_refunds
            WHERE order_id = %s
        """, (order_id,))
        logger.info("check_refund_status | %d Zeilen zurückgegeben", len(result))
        return to_json(result) if result else "Keine Erstattungen für diese Bestellung."
    except Exception:
        logger.error("Fehler in check_refund_status:\n%s", traceback.format_exc())
        raise
    finally:
        conn.close()


@mcp.tool()
async def get_top_products(
    limit: int = Field(10, description="Maximale Anzahl zurückgegebener Produkte"),
    date_from: str = Field(None, description="Startdatum im Format YYYY-MM-DD, z.B. '2014-01-01'"),
    date_to: str = Field(None, description="Enddatum im Format YYYY-MM-DD, z.B. '2014-12-31'"),
) -> str:
    """Gibt die meistverkauften Produkte zurück, optional gefiltert nach Zeitraum (date_from/date_to im Format YYYY-MM-DD)."""
    logger.info("get_top_products aufgerufen | limit=%s date_from=%s date_to=%s", limit, date_from, date_to)
    conn = get_db_connection()
    try:
        query = """
            SELECT p.product_name, COUNT(oi.product_id) as units_sold,
                   SUM(o.price_usd) as total_revenue_usd
            FROM order_items oi
            JOIN products p ON oi.product_id = p.product_id
            JOIN orders o   ON oi.order_id = o.order_id
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

        result = _fetch_all(conn, query, params)
        logger.info("get_top_products | %d Produkte zurückgegeben", len(result))
        return to_json(result) if result else "Keine Daten gefunden."
    except Exception:
        logger.error("Fehler in get_top_products:\n%s", traceback.format_exc())
        raise
    finally:
        conn.close()


@mcp.tool()
async def get_revenue_by_month(
    year: int = Field(..., description="Jahr als vierstellige Zahl, z.B. 2014"),
) -> str:
    """Gibt den monatlichen Umsatzverlauf für ein bestimmtes Jahr zurück."""
    logger.info("get_revenue_by_month aufgerufen | year=%s", year)
    conn = get_db_connection()
    try:
        result = _fetch_all(conn, """
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
        logger.info("get_revenue_by_month | %d Monate zurückgegeben", len(result))
        return to_json(result) if result else f"Keine Daten für {year}."
    except Exception:
        logger.error("Fehler in get_revenue_by_month:\n%s", traceback.format_exc())
        raise
    finally:
        conn.close()


@mcp.tool()
async def get_revenue_by_product() -> str:
    """Gibt den Umsatz gruppiert nach Produkt zurück."""
    logger.info("get_revenue_by_product aufgerufen")
    conn = get_db_connection()
    try:
        result = _fetch_all(conn, """
            SELECT p.product_name,
                   COUNT(oi.product_id) as units_sold,
                   SUM(oi.price_usd) as total_revenue_usd,
                   ROUND(AVG(oi.price_usd)::numeric, 2) as avg_item_price_usd
            FROM order_items oi
            JOIN products p ON oi.product_id = p.product_id
            GROUP BY p.product_name
            ORDER BY total_revenue_usd DESC
        """)
        logger.info("get_revenue_by_product | %d Produkte zurückgegeben", len(result))
        return to_json(result) if result else "Keine Daten gefunden."
    except Exception:
        logger.error("Fehler in get_revenue_by_product:\n%s", traceback.format_exc())
        raise
    finally:
        conn.close()


@mcp.tool()
async def get_conversion_rate_by_source(
    date_from: str = Field(None, description="Startdatum YYYY-MM-DD, optional"),
    date_to: str = Field(None, description="Enddatum YYYY-MM-DD, optional"),
) -> str:
    """Analysiert die Conversion-Rate nach Traffic-Quelle (utm_source): Sessions vs. Kaeufe. Optional filterbar nach Zeitraum (Datensatz: 2012-03-19 bis 2015-03-19)."""
    logger.info("get_conversion_rate_by_source aufgerufen | date_from=%s date_to=%s", date_from, date_to)
    conn = get_db_connection()
    try:
        query = """
            SELECT
                COALESCE(ws.utm_source, 'Unbekannt') as utm_source,
                COUNT(DISTINCT ws.website_session_id) as total_sessions,
                COUNT(DISTINCT o.order_id) as total_orders,
                ROUND(
                    COUNT(DISTINCT o.order_id)::numeric /
                    NULLIF(COUNT(DISTINCT ws.website_session_id), 0) * 100, 2
                ) as conversion_rate_pct
            FROM website_sessions ws
            LEFT JOIN orders o ON ws.website_session_id = o.website_session_id
            WHERE 1=1
        """
        params = []
        if date_from:
            query += " AND ws.created_at >= %s"
            params.append(date_from)
        if date_to:
            query += " AND ws.created_at <= %s"
            params.append(date_to)
        query += " GROUP BY ws.utm_source ORDER BY conversion_rate_pct DESC"
        result = _fetch_all(conn, query, params or None)
        logger.info("get_conversion_rate_by_source | %d Quellen zurueckgegeben", len(result))
        return to_json(result) if result else "Keine Daten gefunden."
    except Exception:
        logger.error("Fehler in get_conversion_rate_by_source:\n%s", traceback.format_exc())
        raise
    finally:
        conn.close()


@mcp.tool()
async def get_device_conversion_rate(
    date_from: str = Field(None, description="Startdatum YYYY-MM-DD, optional"),
    date_to: str = Field(None, description="Enddatum YYYY-MM-DD, optional"),
) -> str:
    """Vergleicht Conversion-Rates zwischen Geraetetypen (Mobile, Desktop, Tablet). Optional filterbar nach Zeitraum (Datensatz: 2012-03-19 bis 2015-03-19)."""
    logger.info("get_device_conversion_rate aufgerufen | date_from=%s date_to=%s", date_from, date_to)
    conn = get_db_connection()
    try:
        query = """
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
            WHERE 1=1
        """
        params = []
        if date_from:
            query += " AND ws.created_at >= %s"
            params.append(date_from)
        if date_to:
            query += " AND ws.created_at <= %s"
            params.append(date_to)
        query += " GROUP BY ws.device_type ORDER BY conversion_rate_pct DESC"
        result = _fetch_all(conn, query, params or None)
        logger.info("get_device_conversion_rate | %d Geraetetypen zurueckgegeben", len(result))
        return to_json(result) if result else "Keine Daten gefunden."
    except Exception:
        logger.error("Fehler in get_device_conversion_rate:\n%s", traceback.format_exc())
        raise
    finally:
        conn.close()


@mcp.tool()
async def get_refund_rate_by_product(
    limit: int = Field(10, description="Maximale Anzahl zurückgegebener Produkte"),
) -> str:
    """Gibt die Produkte mit den höchsten Retourenquoten zurück."""
    logger.info("get_refund_rate_by_product aufgerufen | limit=%s", limit)
    conn = get_db_connection()
    try:
        result = _fetch_all(conn, """
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
        logger.info("get_refund_rate_by_product | %d Produkte zurückgegeben", len(result))
        return to_json(result) if result else "Keine Daten gefunden."
    except Exception:
        logger.error("Fehler in get_refund_rate_by_product:\n%s", traceback.format_exc())
        raise
    finally:
        conn.close()


@mcp.tool()
async def get_repeat_purchase_rate() -> str:
    """Berechnet den Anteil der Kunden, die mehr als einmal bestellt haben."""
    logger.info("get_repeat_purchase_rate aufgerufen")
    conn = get_db_connection()
    try:
        result = _fetch_all(conn, """
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
        logger.info("get_repeat_purchase_rate abgeschlossen")
        return to_json(result) if result else "Keine Daten gefunden."
    except Exception:
        logger.error("Fehler in get_repeat_purchase_rate:\n%s", traceback.format_exc())
        raise
    finally:
        conn.close()


@mcp.tool()
async def generate_period_report(
    von: str = Field(..., description="Startdatum YYYY-MM-DD, z.B. '2014-01-01'"),
    bis: str = Field(..., description="Enddatum YYYY-MM-DD, z.B. '2014-12-31'"),
) -> str:
    """
    Geschaeftsbericht fuer einen Zeitraum. Parameter: von (Startdatum), bis (Enddatum), beide im Format YYYY-MM-DD.
    Beispiel: von='2014-01-01', bis='2014-12-31'.
    """
    date_from = von
    date_to = bis
    logger.info("generate_period_report aufgerufen | date_from=%s date_to=%s", date_from, date_to)
    conn = get_db_connection()
    try:
        logger.debug("generate_period_report | Schritt 1: Umsatz abrufen")
        revenue = _fetch_one(conn, """
            SELECT COUNT(*) as order_count,
                   SUM(price_usd) as revenue_usd,
                   ROUND(AVG(price_usd)::numeric, 2) as avg_order_value_usd
            FROM orders
            WHERE created_at BETWEEN %s AND %s
        """, (date_from, date_to))

        logger.debug("generate_period_report | Schritt 2: Top-5-Produkte abrufen")
        top_products = _fetch_all(conn, """
            SELECT p.product_name, COUNT(*) as units_sold,
                   SUM(oi.price_usd) as revenue_usd
            FROM order_items oi
            JOIN products p ON oi.product_id = p.product_id
            JOIN orders o   ON oi.order_id = o.order_id
            WHERE o.created_at BETWEEN %s AND %s
            GROUP BY p.product_name
            ORDER BY units_sold DESC
            LIMIT 5
        """, (date_from, date_to))

        logger.debug("generate_period_report | Schritt 3: Conversion-Rate abrufen")
        conversion = _fetch_all(conn, """
            SELECT COALESCE(ws.utm_source, 'Unbekannt') as utm_source,
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

        logger.debug("generate_period_report | Schritt 4: Erstattungen abrufen")
        refunds = _fetch_one(conn, """
            SELECT COUNT(*) as refund_count,
                   SUM(refund_amount_usd) as total_refunded_usd
            FROM order_item_refunds
            WHERE created_at BETWEEN %s AND %s
        """, (date_from, date_to))

        report = {
            "zeitraum": f"{date_from} bis {date_to}",
            "umsatz": dict(revenue) if revenue else {},
            "top_produkte": [dict(r) for r in top_products],
            "conversion_nach_quelle": [dict(r) for r in conversion],
            "erstattungen": dict(refunds) if refunds else {},
        }

        logger.info(
            "generate_period_report abgeschlossen | Bestellungen=%s Top-Produkte=%d Quellen=%d",
            revenue.get("order_count") if revenue else "?",
            len(top_products),
            len(conversion),
        )
        return to_json(report)

    except Exception:
        logger.error("Fehler in generate_period_report:\n%s", traceback.format_exc())
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    logger.info("Starte toy-store-mcp Server auf 0.0.0.0:8000 (streamable-http) ...")
    uvicorn.run(mcp.streamable_http_app(), host="0.0.0.0", port=8000)
