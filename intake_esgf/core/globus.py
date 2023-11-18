"""A Globus-based ESGF1 style index."""
import re
import time
from pathlib import Path
from typing import Any, Union

import pandas as pd
from globus_sdk import SearchClient

from intake_esgf.base import get_dataset_pattern


class GlobusESGFIndex:
    GLOBUS_INDEX_IDS = {
        "anl-dev": "d927e2d9-ccdb-48e4-b05d-adbc3d97bbc5",
    }

    def __init__(self, index_id="anl-dev"):
        self.repr = f"GlobusESGFIndex('{index_id}')"
        if index_id in GlobusESGFIndex.GLOBUS_INDEX_IDS:
            index_id = GlobusESGFIndex.GLOBUS_INDEX_IDS[index_id]
        self.index_id = index_id
        self.client = SearchClient()
        self.logger = None

    def __repr__(self):
        return self.repr

    def search(self, **search: Union[str, list[str]]) -> pd.DataFrame:
        # We need to implement the pagination here, I am just using a large limit for
        # now but that isn't safe and I am not sure of performance implications.
        total_time = time.time()
        limit = 2000
        if "project" in search:
            project = search.pop("project")
            if project != "CMIP6":
                raise ValueError("ANL Globus index only for CMIP6")
        search["type"] = "Dataset"
        if "latest" not in search:
            search["latest"] = True
        for key, val in search.items():
            if isinstance(val, bool):
                search[key] = str(val)
        query_data = {
            "q": "",
            "filters": [
                {
                    "type": "match_any",
                    "field_name": key,
                    "values": [val] if isinstance(val, str) else val,
                }
                for key, val in search.items()
            ],
            "facets": [],
            "sort": [],
        }
        response_time = time.time()
        response = SearchClient().post_search(self.index_id, query_data, limit=limit)
        response_time = time.time() - response_time
        if not response["total"]:
            if self.logger is not None:
                self.logger.info(f"└─{self} no results")
            raise ValueError("Search returned no results.")
        pattern = get_dataset_pattern()
        df = []
        for g in response["gmeta"]:
            m = re.search(pattern, g["subject"])
            if m:
                df.append(m.groupdict())
                df[-1]["id"] = g["subject"]
        df = pd.DataFrame(df)
        total_time = time.time() - total_time
        if self.logger is not None:
            self.logger.info(f"└─{self} {response_time=:.2f} {total_time=:.2f}")
        return df

    def get_file_info(self, dataset_ids: list[str]) -> dict[str, Any]:
        """"""
        response = SearchClient().post_search(
            self.index_id,
            {
                "q": "",
                "filters": [
                    {
                        "type": "match_any",
                        "field_name": "dataset_id",
                        "values": dataset_ids,
                    }
                ],
                "facets": [],
                "sort": [],
            },
            limit=1000,
        )
        infos = []
        for g in response["gmeta"]:
            info = {}
            assert len(g["entries"]) == 1
            entry = g["entries"][0]
            if entry["entry_id"] != "file":
                continue
            content = entry["content"]
            info["checksum_type"] = content["checksum_type"][0]
            info["checksum"] = content["checksum"][0]
            info["size"] = content["size"]
            for url in content["url"]:
                link, link_type = url.split("|")
                if link_type not in info:
                    info[link_type] = []
                info[link_type].append(link)
            # For some reason, the `version` in the globus response is just an integer
            # and not what is used in the file path so I have to parse it out of the
            # `dataset_id`
            content["version"] = [content["dataset_id"].split("|")[0].split(".")[-1]]
            file_path = content["directory_format_template_"][0]
            info["path"] = (
                Path(
                    file_path.replace("%(root)s/", "")
                    .replace("%(", "{")
                    .replace(")s", "[0]}")
                    .format(**content)
                )
                / content["title"]
            )
            infos.append(info)
        return infos

    def from_tracking_ids(self, tracking_ids: Union[str, list[str]]) -> pd.DataFrame:
        if isinstance(tracking_ids, str):
            tracking_ids = [tracking_ids]
        response = SearchClient().post_search(
            self.index_id,
            {
                "q": "",
                "filters": [
                    {
                        "type": "match_any",
                        "field_name": "tracking_id",
                        "values": tracking_ids,
                    }
                ],
                "facets": [],
                "sort": [],
            },
            limit=1000,
        )
        pattern = get_dataset_pattern()
        df = []
        for g in response["gmeta"]:
            try:
                dataset_id = g["entries"][0]["content"]["dataset_id"]
            except Exception:
                continue
            m = re.search(pattern, dataset_id)
            if m:
                df.append(m.groupdict())
                df[-1]["id"] = dataset_id
        df = pd.DataFrame(df)
        return df
