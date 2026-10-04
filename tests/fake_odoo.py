"""In-memory stand-in for the Odoo XML-RPC object API, enough for pulse.odoo.pull."""
from datetime import datetime, timedelta, timezone

ORDER_FIELDS = {
    "name": {"string": "Order Reference", "type": "char"},
    "date_order": {"string": "Order Date", "type": "datetime"},
    "amount_total": {"string": "Total", "type": "monetary"},
    "state": {"string": "Status", "type": "selection", "selection": [["draft", "Quotation"], ["sale", "Sales Order"], ["cancel", "Cancelled"]]},
    "invoice_status": {"string": "Invoice Status", "type": "selection"},
    "partner_id": {"string": "Customer", "type": "many2one", "relation": "res.partner"},
    "user_id": {"string": "Salesperson", "type": "many2one", "relation": "res.users"},
    "campaign_id": {"string": "Campaign", "type": "many2one", "relation": "utm.campaign"},
    "source_id": {"string": "Source", "type": "many2one", "relation": "utm.source"},
    "medium_id": {"string": "Medium", "type": "many2one", "relation": "utm.medium"},
    "x_magento_id": {"string": "Magento Order ID", "type": "char"},
    "magento_status_std": {"string": "Order Status", "type": "char"},
    "x_order_status": {"string": "Order Status", "type": "char"},
    "x_sellers": {"string": "Sellers", "type": "many2many", "relation": "res.partner"},
    "x_store": {"string": "Store Based ID", "type": "char"},
    "x_wilaya": {"string": "Wilaya", "type": "char"},
    "x_utm_content": {"string": "UTM Content", "type": "char"},
}
LINE_FIELDS = {
    "order_id": {"string": "Order", "type": "many2one"},
    "product_id": {"string": "Product", "type": "many2one"},
    "product_uom_qty": {"string": "Quantity", "type": "float"},
    "price_total": {"string": "Total", "type": "monetary"},
    "x_seller": {"string": "Seller", "type": "many2one"},
    "x_category": {"string": "Product Category", "type": "char"},
}


def utc(days_ago, hour=12):
    d = datetime.now(timezone.utc).replace(hour=hour, minute=0, second=0, microsecond=0) - timedelta(days=days_ago)
    return d.strftime("%Y-%m-%d %H:%M:%S")


class FakeOdoo:
    def __init__(self, n=2500, fail=False):
        self.calls = []
        self.fail = fail
        self.sleeps = []
        self.orders = []
        statuses = ["Delivered", "Expédiée", "pending", "Canceled", "Refusé", "processing"]
        for i in range(n):
            self.orders.append({
                "id": i + 1, "name": f"S{i:05d}", "date_order": utc(i % 80, hour=(i * 7) % 24), "amount_total": 4500.0,
                "state": "cancel" if i % 50 == 0 else "sale", "invoice_status": "no", "partner_id": [i + 1, f"Client {i}"],
                "user_id": False, "campaign_id": [1, "Lampes"] if i % 2 else False, "source_id": [1, "fb"] if i % 2 else False,
                "medium_id": False, "x_magento_id": f"1000{i}", "magento_status_std": "ignored",
                "x_order_status": statuses[i % len(statuses)], "x_sellers": [101, 102] if i % 3 == 0 else [101],
                "x_store": "Hamiz Web", "x_wilaya": "Alger", "x_utm_content": "T_lamp_TOFU_demo_v1" if i % 4 == 1 else False,
            })

    def sleep(self, s):
        self.sleeps.append(s)

    def call(self, model, method, *args, **kw):
        self.calls.append((model, method))
        if self.fail:
            raise OSError("connection refused")
        if method == "fields_get":
            return ORDER_FIELDS if model == "sale.order" else LINE_FIELDS
        if method == "read":
            return [{"id": i, "display_name": {101: "Mode Tlemcen", 102: "Sport Atlas"}[i]} for i in args[0]]
        if method == "search_read":
            domain = args[0]
            offset, limit = kw.get("offset", 0), kw.get("limit", 1000)
            if model == "sale.order":
                since = domain[0][2]
                rows = [{k: o[k] for k in kw["fields"]} | {"id": o["id"]} for o in self.orders if o["date_order"] >= since]
                return rows[offset:offset + limit]
            ids = set(domain[0][2])
            rows = [{"order_id": [o["id"], o["name"]], "product_id": [7, "Lampe LED"], "product_uom_qty": 1.0,
                     "price_total": 4500.0, "x_seller": [101, "Mode Tlemcen"], "x_category": "Maison"}
                    for o in self.orders if o["id"] in ids]
            return rows[offset:offset + limit]
        raise AssertionError(method)

    def search_read(self, model, domain, fields, order="id asc"):
        from pulse.odoo import Odoo
        return Odoo.search_read(self, model, domain, fields, order)

    def fields(self, model):
        return self.call(model, "fields_get")

    def names(self, model, ids):
        from pulse.odoo import Odoo
        return Odoo.names(self, model, ids)
