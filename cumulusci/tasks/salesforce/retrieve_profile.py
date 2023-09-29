from cumulusci.salesforce_api.metadata import ApiRetrieveUnpackaged
from cumulusci.tasks.salesforce.BaseSalesforceMetadataApiTask import (
    BaseSalesforceMetadataApiTask,
)


class RetrieveProfile(BaseSalesforceMetadataApiTask):
    api_class = ApiRetrieveUnpackaged
    task_options = {
        "name": {
            "description": "The name of the the new profile",
            "required": True,
        },
    }

    def _init_options(self, kwargs):
        super(RetrieveProfile, self)._init_options(kwargs)

    def _run_task(self):

        self.name = self.options["name"]

        self.package_xml = f"""
        <?xml version="1.0" encoding="UTF-8"?>
        <Package xmlns="http://soap.sforce.com/2006/04/metadata">
            <types>
                <members>{self.name}</members>
                <name>Profile</name>
            </types>
            <version>54.0</version>
        </Package>
        """

        api = self._get_api()
        zip_result = api()
        zip_result.extractall("./unpackaged")
        self.logger.info(f"Profile '{self.name}' unzipped into folder 'unpackaged'")

    def _get_api(self):
        return self.api_class(
            self,
            api_version=self.org_config.latest_api_version,
            package_xml=self.package_xml,
        )
