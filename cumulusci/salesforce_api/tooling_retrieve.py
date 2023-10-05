import json
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Union

from salesforce_bulk.util import IteratorBytesIO
from simple_salesforce.exceptions import SalesforceGeneralError

from cumulusci.tasks.salesforce.BaseSalesforceApiTask import BaseSalesforceApiTask


class MetadataInfo:
    def __init__(
        self, columns: List[str], table_name: str, package_xml_name: str, id_field: str
    ):
        self.columns = columns
        self.table_name = table_name
        self.package_xml_name = package_xml_name
        self.id_field = id_field


APEXCLASS = MetadataInfo(
    columns=["Name", "NamespacePrefix"],
    table_name="ApexClass",
    package_xml_name="ApexClass",
    id_field="Id",
)
APEXPAGE = MetadataInfo(
    columns=["Name", "NamespacePrefix"],
    table_name="ApexPage",
    package_xml_name="ApexPage",
    id_field="Id",
)
CUSTOMPERMISSION = MetadataInfo(
    columns=["DeveloperName", "NamespacePrefix"],
    table_name="CustomPermission",
    package_xml_name="CustomPermission",
    id_field="Id",
)
TABSET = MetadataInfo(
    columns=["Name", "NamespacePrefix"],
    table_name="AppMenuItem",
    package_xml_name="CustomApplication",
    id_field="ApplicationId",
)
CONNECTEDAPPLICATION = MetadataInfo(
    columns=["Name", "NamespacePrefix"],
    table_name="AppMenuItem",
    package_xml_name="CustomApplication",
    id_field="ApplicationId",
)
EXTERNALDATASOURCE = MetadataInfo(
    columns=["DeveloperName", "NamespacePrefix"],
    table_name="ExternalDataSource",
    package_xml_name="ExternalDataSource",
    id_field="Id",
)
FLOWDEFINITION = MetadataInfo(
    columns=["ApiName"],
    table_name="FlowDefinitionView",
    package_xml_name="Flow",
    id_field="Id",
)

SETUP_ENTITY_TYPES = {
    "ApexClass": APEXCLASS,
    "ApexPage": APEXPAGE,
    "CustomPermission": CUSTOMPERMISSION,
    "TabSet": TABSET,
    "ConnectedApplication": CONNECTEDAPPLICATION,
    "ExternalDataSource": EXTERNALDATASOURCE,
    "FlowDefinition": FLOWDEFINITION,
}
SETUP_ENTITY_QUERY_NAME = "setupEntityAccess"

SOBJECT_TYPE = "CustomObject"
SOBJECT_QUERY_NAME = "sObject"

CUSTOM_TAB_TYPE = "CustomTab"
CUSTOM_TAB_QUERY_NAME = "customTab"


class ToolingApiTask(BaseSalesforceApiTask):
    def _init_task(self):
        self.api_version = "58.0"
        super(ToolingApiTask, self)._init_task()

    def _run_queries_in_parallel(self, queries: Dict[str, str]) -> Dict[str, list]:
        num_threads = 4
        results_dict = {}

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = {
                query_name: executor.submit(self._run_query, query)
                for query_name, query in queries.items()
            }

        for query_name, future in futures.items():
            try:
                query_result = future.result()
                results_dict[query_name] = query_result["records"]
            except Exception as e:
                raise Exception(f"Error executing query '{query_name}': {type(e)}: {e}")
            else:
                queries.pop(query_name, None)

        return results_dict

    def _run_query(self, query):
        try:
            result = self.sf.query(query)
        except SalesforceGeneralError:
            result = self._run_bulk_query(query)
        return result

    def _run_bulk_query(self, query):
        table_name = self._extract_table_name_from_query(query)
        job = self.bulk.create_query_job(table_name, contentType="JSON")

        batch = self.bulk.query(job, query)
        self.bulk.wait_for_batch(job, batch)
        self.bulk.close_job(job)
        results = self.bulk.get_all_results_for_query_batch(batch)
        for result in results:
            result = json.load(IteratorBytesIO(result))
            return {"records": result}

    def _extract_table_name_from_query(self, query):
        from_index = query.upper().find("FROM")
        if from_index != -1:
            query = query[from_index + len("FROM") :].strip()
            table_name = query.split()[0]
            return table_name
        else:
            raise ValueError("Invalid query format. 'FROM' clause not found.")

    def _build_query(
        self,
        columns: List[str],
        table_name: str,
        where: Dict[str, Union[str, List[str]]] = None,
    ) -> str:
        if not columns:
            raise ValueError("Columns list cannot be empty")
        if not table_name:
            raise ValueError("Table name cannot be empty")

        select_clause = ", ".join(columns)

        where_clause = ""
        if where:
            where_list = []
            for key, value in where.items():
                if isinstance(value, list):
                    value = ", ".join([f"'{item}'" for item in value])
                    condition = f"{key} IN ({value})"
                else:
                    condition = f"{key} = '{value}'"
                where_list.append(condition)
            where_clause = "WHERE " + " AND ".join(where_list)

        query = f"SELECT {select_clause} FROM {table_name} {where_clause}"
        return query

    # Retrieve all the permissionable entitites for a set of profiles
    def _retrieve_permissionable_entities(self, profiles: List[str]):
        queries = {}

        # Setup Entity Access query
        setupEntityAccess_query = self._build_query(
            ["SetupEntityId", "SetupEntityType"],
            "SetupEntityAccess",
            {"Parent.Profile.Name": profiles},
        )
        queries[SETUP_ENTITY_QUERY_NAME] = setupEntityAccess_query

        # sObject query
        sObject_query = self._build_query(
            ["SObjectType"], "ObjectPermissions", {"Parent.Profile.Name": profiles}
        )
        queries[SOBJECT_QUERY_NAME] = sObject_query

        # Custom Tab query
        customTab_query = self._build_query(
            ["Name"], "PermissionSetTabSetting", {"Parent.Profile.Name": profiles}
        )
        queries[CUSTOM_TAB_QUERY_NAME] = customTab_query

        # Run all queries
        result = self._run_queries_in_parallel(queries)

        # Process the results
        permissionable_entities = {}
        permissionable_entities.update(
            self._process_setupEntityAccess_results(result[SETUP_ENTITY_QUERY_NAME])
        )
        permissionable_entities.update(
            self._process_sObject_results(result[SOBJECT_QUERY_NAME])
        )
        permissionable_entities.update(
            self._process_customTab_results(result[CUSTOM_TAB_QUERY_NAME])
        )

        return permissionable_entities

    def _process_setupEntityAccess_results(self, result_list: List[dict]):
        setupEntityAccess_dict = {
            entity_type: [] for entity_type in SETUP_ENTITY_TYPES.keys()
        }

        for data in result_list:
            entity_type = data["SetupEntityType"]
            entity_id = data["SetupEntityId"]
            if entity_type in SETUP_ENTITY_TYPES.keys():
                setupEntityAccess_dict[entity_type].append(entity_id)

        queries = {}
        for entity_type, query_values in SETUP_ENTITY_TYPES.items():
            if query_values and len(setupEntityAccess_dict[entity_type]) != 0:
                queries[entity_type] = self._build_query(
                    query_values.columns,
                    query_values.table_name,
                    {query_values.id_field: setupEntityAccess_dict[entity_type]},
                )

        result = self._run_queries_in_parallel(queries)

        extracted_values = {}
        for entity_type, data in SETUP_ENTITY_TYPES.items():
            if entity_type in result and data:
                extracted_values.setdefault(data.package_xml_name, [])
                for item in result[entity_type]:
                    if (
                        "NamespacePrefix" in item
                        and item["NamespacePrefix"] is not None
                    ):
                        extracted_values[data.package_xml_name].append(
                            f'{item["NamespacePrefix"]}__{item[data.columns[0]]}'
                        )
                    else:
                        extracted_values[data.package_xml_name].append(
                            item[data.columns[0]]
                        )

        return extracted_values

    def _process_sObject_results(self, result_list: List[dict]):
        sObject_list = [data["SobjectType"] for data in result_list]
        return {SOBJECT_TYPE: sObject_list}

    def _process_customTab_results(self, result_list: List[dict]):
        customTab_list = [data["Name"] for data in result_list]
        return {CUSTOM_TAB_TYPE: customTab_list}
