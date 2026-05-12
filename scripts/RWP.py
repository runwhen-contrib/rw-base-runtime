"""
RunWhen Platform keyword library

Scope: Global
"""
import re
from typing import Optional
from robot.libraries.BuiltIn import BuiltIn
from . import utils


class RWP:
    """RunWhen Platform keyword library"""

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    def __init__(self, auth_session: Optional[bool] = False):
        self.session = None

        BuiltIn().import_library("RW.Core")
        BuiltIn().import_library("RW.HTTP")
        BuiltIn().import_library("RW.Report")
        BuiltIn().import_library("RW.K8s")

        self.rw_core = BuiltIn().get_library_instance("RW.Core")
        self.rw_http = BuiltIn().get_library_instance("RW.HTTP")
        self.rw_report = BuiltIn().get_library_instance("RW.Report")
        self.rw_k8s = BuiltIn().get_library_instance("RW.K8s")

        self.bs_endpoint = utils.import_user_variable("BACKEND_SERVICES_ENDPOINT")
        self.bs_user = None
        try:
            self.bs_user = utils.import_user_variable("BACKEND_SERVICES_USER_NAME")
        except Exception:
            platform.debug_log("User variable BACKEND_SERVICES_USER_NAME is not defined.")

        self.bs_password = None
        try:
            self.bs_password = utils.import_user_variable("BACKEND_SERVICES_PASSWORD")
        except Exception:
            platform.debug_log("User variable BACKEND_SERVICES_PASSWORD is not defined.")

        self.workspace_name = None
        try:
            self.workspace_name = utils.import_user_variable("WORKSPACE_NAME")
        except Exception:
            platform.debug_log("User variable WORKSPACE_NAME is not defined.")

        self.slx_name = None
        try:
            self.slx_name = utils.import_user_variable("SLX_NAME")
        except Exception:
            platform.debug_log("User variable SLX_NAME is not defined.")

        self.kubeconfig = None
        try:
            self.kubeconfig = utils.import_user_variable("KUBECONFIG")
            self.rw_k8s.set_kubeconfig(self.kubeconfig)
        except Exception:
            platform.debug_log("User variable KUBECONFIG is not defined.")

        auth_session = utils.to_bool(auth_session)
        if auth_session is True:
            self.get_backend_services_authenticated_session()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.session is not None:
            self.rw_http.close_session(self.session)

    def get_backend_services_authenticated_session(self):
        try:
            self.session = self.rw_http.create_authenticated_session(
                url=f"{self.bs_endpoint}/api/v3/token/",
                user=self.bs_user,
                password=self.bs_password,
            )
            return "success"
        except Exception:
            self.add_report_fatal_error("backend-services authentication: fatal error")

    def get_workspaces_info(self):
        res = self.rw_http.get(
            f"{self.bs_endpoint}/api/v3/workspaces",
            session=self.session,
        )
        platform.debug_log(utils.prettify(res.json()))
        if res.status_code != 200:
            self.add_report_and_fatal_error("Unable to retrieve workspaces" " (HTTTP status: {res.status_code})")
        return res

    def get_sli_info(self):
        res = self.rw_http.get(
            f"{self.bs_endpoint}/api/v3/workspaces/{self.workspace_name}" + f"/slxs/{self.slx_name}/sli",
            session=self.session,
        )
        platform.debug_log(utils.prettify(res.json()))
        if res.status_code != 200:
            self.add_report_and_fatal_error(
                "Workspace, SLX, or SLI is not defined" " (HTTTP status: {res.status_code})"
            )
        return res

    def get_sli_name(self):
        return self.get_sli_info().json()["name"]

    def get_sli_location(self):
        res = self.get_sli_info().json()
        if "locations" not in res["spec"]:
            self.add_report_and_task_failure("SLI location: undefined")
        return res["spec"]["locations"][0]

    def get_sli_running_status(self):
        location = self.get_sli_location()
        res = self.rw_http.get(
            f"{self.bs_endpoint}/api/v3/workspaces/{self.workspace_name}" + f"/slxs/{self.slx_name}/sli/locations",
            session=self.session,
        )
        platform.debug_log(utils.prettify(res.json()))
        if res.status_code != 200:
            self.add_report_and_fatal_error("SLI running status failed" " (HTTTP status: {res.status_code})")
        return res.json()[location]["phase"]

    def get_cortex_info(self, soft_error=False):
        res = self.rw_http.get(
            f"{self.bs_endpoint}/api/v3/workspaces/{self.workspace_name}" + f"/slxs/{self.slx_name}/sli/recent",
            session=self.session,
        )
        platform.debug_log(utils.prettify(res.json()))
        if res.status_code != 200 and soft_error is False:
            self.add_report_and_fatal_error("Failed to retrieve Cortex info" " (HTTTP status: {res.status_code})")
        return res

    def get_cortex_result(self):
        res = self.get_cortex_info()
        return res.json()["data"]["result"]

    def get_metrics_from_cortex(self):
        res = self.get_cortex_info(soft_error=True)
        if res.status_code not in [200]:
            platform.error_log(f"Cortex get metrics received HTTP status {res.status_code}." + " No metrics found.")
            return []
        else:
            return res.json()["data"]["result"][0]["values"]

    def add_report_and_fatal_error(self, msg):
        self.rw_report.add_to_report(f"* {msg}")
        raise core.FatalError(msg)

    def add_report_and_task_failure(self, msg):
        self.rw_report.add_to_report(f"* {msg}")
        raise core.FatalError(msg)

    def get_backend_services_hostname(self):
        return self.rw_core.get_hostname_from_url(self.bs_endpoint)

    def get_kbs_devkit_pod_name(self):
        """Return the name of the DevKit pod."""
        res = self.rw_k8s.kubectl("get pods --field-selector=status.phase=Running -n backend-services")
        platform.debug_log(res)
        matched_lines = re.findall("^devkit.*", res["stdout"], re.MULTILINE)
        pod_name = matched_lines[0].split()[0]
        return pod_name

    def get_pod_image_name_from_output(self, output):
        matched_lines = re.findall(".*Image:.*", output, re.MULTILINE)
        image = matched_lines[0].split()[1]
        return image

    def get_errors_from_output(self, output):
        # Note: The flags "re.MULTILINE | re.IGNORECASE" will produce lots of
        # non-relevant results.
        matched_lines = re.findall(".*ERROR.*", output, re.MULTILINE)
        return matched_lines
