from cumulusci.core.utils import process_list_arg
from cumulusci.salesforce_api.metadata import ApiRetrieveUnpackaged
from cumulusci.salesforce_api.tooling_retrieve import ToolingApiTask
from cumulusci.tasks.salesforce.BaseSalesforceMetadataApiTask import (
    BaseSalesforceMetadataApiTask,
)

EXTRACT_DIR = "./unpackaged"


class RetrieveProfile(BaseSalesforceMetadataApiTask):
    api_class = ApiRetrieveUnpackaged
    task_options = {
        "profiles": {
            "description": "List of profiles that you want to retrieve",
            "required": True,
        },
    }

    def _init_options(self, kwargs):
        super(RetrieveProfile, self)._init_options(kwargs)

    def _run_task(self):

        self.profiles = process_list_arg(self.options["profiles"])
        self.tooling_task = ToolingApiTask(
            project_config=self.project_config,
            task_config=self.task_config,
            org_config=self.org_config,
        )
        self.tooling_task._init_task()
        permissionable_entities = self.tooling_task._retrieve_permissionable_entities(
            self.profiles
        )
        entities_to_be_retrieved = {
            **permissionable_entities,
            **{"Profile": self.profiles},
        }

        self.package_xml = self._create_package_xml(entities_to_be_retrieved)
        api = self._get_api()
        zip_result = api()
        # for file_info in zip_result.infolist():
        #     if file_info.filename.startswith("profiles/"):
        #         zip_result.extract(file_info, EXTRACT_DIR)
        zip_result.extractall("./unpackaged")
        self.logger.info(
            f"Profiles '{self.profiles}' unzipped into folder 'unpackaged'"
        )

    def _get_api(self):
        return self.api_class(
            self,
            api_version=self.org_config.latest_api_version,
            package_xml=self.package_xml,
        )

    def _create_package_xml(self, input_dict: dict, api_version="58.0"):
        package_xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
        package_xml += '<Package xmlns="http://soap.sforce.com/2006/04/metadata">\n'

        for name, members in input_dict.items():
            package_xml += "    <types>\n"
            for member in members:
                package_xml += f"        <members>{member}</members>\n"
            package_xml += f"        <name>{name}</name>\n"
            package_xml += "    </types>\n"

        package_xml += f"    <version>{api_version}</version>\n"
        package_xml += "</Package>\n"

        return package_xml
