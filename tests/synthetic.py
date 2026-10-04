"""The reference --selftest input, reproduced exactly (same seed, same draws)."""
import random
from datetime import datetime, timedelta

from pulse.config import DZ


def selftest_input(n=6000, seed=7, n_sellers=39, n_products=300):
    random.seed(seed)
    now = datetime(2026, 10, 4, 13, 0, tzinfo=DZ)
    stores = ["Hamiz Web", "Hamiz App", "Facebook"]
    sellers = [f"Seller {i}" for i in range(1, n_sellers + 1)]
    orders, lines = [], []
    for i in range(n):
        dt = now - timedelta(days=random.random() * 90, hours=random.random() * 3)
        stage = random.choices(["pending", "confirmed", "delivered", "cancelled", "returned"], [5, 15, 50, 22, 8])[0]
        ref = f"S{i:05d}"
        ss = random.sample(sellers, random.choice([1, 1, 1, 2]))
        tot = random.choice([2500, 3900, 4500, 6200, 7900, 12000])
        orders.append({"id": i, "ref": ref, "magento": f"10000{i}", "dt": dt, "total": tot, "stage": stage,
                       "status_raw": stage, "customer": f"Client {i % 900}", "salesperson": None,
                       "store": random.choice(stores), "sellers": ss, "source": random.choice(["Facebook", None]),
                       "campaign": random.choice(["Rentree", "Lampes", None]), "wilaya": None})
        for s in ss:
            lines.append({"order_ref": ref, "product": f"Produit {random.randint(1, n_products)}", "qty": 1,
                          "amount": tot / len(ss), "seller": s, "category": "Maison"})
    return orders, lines, now
