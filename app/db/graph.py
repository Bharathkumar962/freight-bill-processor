import json
import networkx as nx
from datetime import date
from pathlib import Path

G: nx.DiGraph = nx.DiGraph()
_seed_data: dict = {}

def load_graph(seed_path: str = "seed_data_logistics.json"):
    global G, _seed_data
    path = Path(seed_path)
    if not path.exists():
        path = Path(__file__).parents[2] / seed_path
    with open(path) as f:
        _seed_data = json.load(f)
    G = nx.DiGraph()
    for c in _seed_data["carriers"]:
        G.add_node(c["id"], type="carrier", **c)
    for cc in _seed_data["carrier_contracts"]:
        G.add_node(cc["id"], type="contract", **cc)
        G.add_edge(cc["carrier_id"], cc["id"], rel="HAS_CONTRACT")
        for rate in cc.get("rate_card", []):
            lane_node_id = f"{cc['id']}::{rate['lane']}"
            rate_copy = {k: v for k, v in rate.items() if k != "lane"}
            G.add_node(lane_node_id, type="lane", lane=rate["lane"], contract_id=cc["id"], **rate_copy)
            G.add_edge(cc["id"], lane_node_id, rel="COVERS_LANE")
    for s in _seed_data["shipments"]:
        G.add_node(s["id"], type="shipment", **s)
        G.add_edge(s["carrier_id"], s["id"], rel="HAS_SHIPMENT")
        G.add_edge(s["contract_id"], s["id"], rel="LINKED_TO_SHIPMENT")
    for b in _seed_data["bills_of_lading"]:
        G.add_node(b["id"], type="bol", **b)
        G.add_edge(b["shipment_id"], b["id"], rel="HAS_BOL")
    return G

def get_carrier(carrier_id: str):
    if carrier_id in G and G.nodes[carrier_id].get("type") == "carrier":
        return dict(G.nodes[carrier_id])
    return None

def find_carrier_by_name(name: str):
    name_lower = name.lower()
    for node_id, data in G.nodes(data=True):
        if data.get("type") == "carrier":
            if data.get("name", "").lower() == name_lower:
                return {"id": node_id, **data}
    return None

def get_contracts_for_carrier(carrier_id: str):
    contracts = []
    for _, neighbor, edge_data in G.out_edges(carrier_id, data=True):
        if edge_data.get("rel") == "HAS_CONTRACT":
            contracts.append({"id": neighbor, **G.nodes[neighbor]})
    return contracts

def get_active_contracts_for_lane(carrier_id: str, lane: str, bill_date: str):
    bill_dt = date.fromisoformat(bill_date)
    results = []
    for contract in get_contracts_for_carrier(carrier_id):
        c_id = contract["id"]
        eff = date.fromisoformat(contract["effective_date"])
        exp = date.fromisoformat(contract["expiry_date"])
        if not (eff <= bill_dt <= exp):
            continue
        if contract.get("status") != "active":
            continue
        for _, lane_node_id, edge_data in G.out_edges(c_id, data=True):
            if edge_data.get("rel") == "COVERS_LANE":
                lane_data = G.nodes[lane_node_id]
                if lane_data.get("lane") == lane:
                    results.append({"contract": contract, "rate": dict(lane_data)})
    results.sort(key=lambda x: x["contract"]["effective_date"], reverse=True)
    return results

def get_shipment(shipment_id: str):
    if shipment_id in G and G.nodes[shipment_id].get("type") == "shipment":
        return dict(G.nodes[shipment_id])
    return None

def get_bols_for_shipment(shipment_id: str):
    bols = []
    for _, neighbor, edge_data in G.out_edges(shipment_id, data=True):
        if edge_data.get("rel") == "HAS_BOL":
            bols.append({"id": neighbor, **G.nodes[neighbor]})
    return bols

def get_all_shipments_for_contract(contract_id: str):
    shipments = []
    for _, neighbor, edge_data in G.out_edges(contract_id, data=True):
        if edge_data.get("rel") == "LINKED_TO_SHIPMENT":
            shipments.append({"id": neighbor, **G.nodes[neighbor]})
    return shipments

def get_raw_seed():
    return _seed_data
