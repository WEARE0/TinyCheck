#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from app import db
from app.db.models import MISPInst
from sqlalchemy.sql import exists
from app.definitions import definitions as defs
from urllib.parse import unquote
from flask import escape
from pymisp import PyMISP
import re
import time
import sys


class MISP(object):
    def __init__(self):
        return None

    def add_instance(self, instance):
        """
            Parse and add a MISP instance to the database.
            :return: status of the operation in JSON
        """

        url = instance["url"]
        name = instance["name"]
        apikey = instance["key"]
        verify = instance["ssl"]

        sameinstances = db.session.query(MISPInst).filter(
            MISPInst.url == url, MISPInst.apikey == apikey)
        if sameinstances.count():
            return {"status": False,
                    "message": "This MISP instance already exists"}
        if name:
            if self.test_instance(url, apikey, verify):
                added_on = int(time.time())
                db.session.add(MISPInst(name, escape(url), apikey, verify, added_on))
                db.session.commit()
                return {"status": True,
                        "message": "MISP instance added",
                        "name": escape(name),
                        "url": escape(url),
                        "apikey": escape(apikey),
                        "verifycert": escape(verify)}
            else:
                return {"status": False,
                        "message": "Please verify the connection to the MISP instance"}
        else:
            return {"status": False,
                    "message": "Please provide a name for your instance"}

    @staticmethod
    def delete_instance(misp_id):
        """
            Delete a MISP instance by its id in the database.
            :return: status of the operation in JSON
        """
        if db.session.query(exists().where(MISPInst.id == misp_id)).scalar():
            db.session.query(MISPInst).filter_by(id=misp_id).delete()
            db.session.commit()
            return {"status": True,
                    "message": "MISP instance deleted"}
        else:
            return {"status": False,
                    "message": "MISP instance not found"}

    def get_instances(self):
        """
            Get MISP instances from the database
            :return: generator of the records.
        """
        for misp in db.session.query(MISPInst).all():
            misp = misp.__dict__
            yield {"id": misp["id"],
                   "name": misp["name"],
                   "url": misp["url"],
                   "apikey": misp["apikey"],
                   "verifycert": True if misp["verifycert"] else False,
                   "connected": self.test_instance(misp["url"], misp["apikey"], misp["verifycert"]) }

    @staticmethod
    def test_instance(url, apikey, verify):
        """
            Test the connection of the MISP instance.
            :return: generator of the records.
        """
        try:
            PyMISP(url, apikey, verify)
            return True
        except:
            return False

    @staticmethod
    def get_iocs(misp_id):
        """
            Get all IOCs from specific MISP instance
            /!\ Todo: NEED TO ADD LAST SYNCHRO DATE + page etc. stuff.
            :return: generator containing the IOCs.
        """
        misp = MISPInst.query.get(int(misp_id))
        if misp is not None:
            if misp.url and misp.apikey:
                try:
                    # Connect to MISP instance and get network activity attributes.
                    m = PyMISP(misp.url, misp.apikey, misp.verifycert)
                    r = m.search("attributes", category="Network activity")
                except:
                    print("Unable to connect to the MISP instance ({}/{}).".format(misp.url, misp.apikey))
                    return []

                for attr in r["Attribute"]:
                    if attr["type"] in ["ip-dst", "domain", "snort", "x509-fingerprint-sha1"]:

                        ioc = {"value": attr["value"],
                               "type": None,
                               "tag": "suspect",
                               "tlp": "white"}

                        # Deduce the IOC type.
                        if re.match(defs["iocs_types"][0]["regex"], attr["value"]):
                            ioc["type"] = "ip4addr"
                        elif re.match(defs["iocs_types"][1]["regex"], attr["value"]):
                            ioc["type"] = "ip6addr"
                        elif re.match(defs["iocs_types"][2]["regex"], attr["value"]):
                            ioc["type"] = "cidr"
                        elif re.match(defs["iocs_types"][3]["regex"], attr["value"]):
                            ioc["type"] = "domain"
                        elif re.match(defs["iocs_types"][4]["regex"], attr["value"]):
                            ioc["type"] = "sha1cert"
                        elif "alert " in attr["value"][0:6]:
                            ioc["type"] = "snort"
                        else:
                            continue

                        if "Tag" in attr:
                            for tag in attr["Tag"]:
                                # Add a TLP to the IOC if defined in tags.
                                tlp = re.search(r"^(?:tlp:)(red|green|amber|white)", tag['name'].lower())
                                if tlp: ioc["tlp"] = tlp.group(1)

                                # Add possible tag (need to match TinyCheck tags)
                                if tag["name"].lower() in [t["tag"] for t in defs["iocs_tags"]]:
                                    ioc["tag"] = tag["name"].lower()
                        yield ioc
