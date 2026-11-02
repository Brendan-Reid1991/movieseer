from docker import DockerClient
from docker.context import ContextAPI
from docker.models.networks import Network as DockerNetwork
from docker.models.containers import Container as DockerContainer

from woodstock.service_apis.data_structures.docker_models import ContainerState

CURRENT_CONTEXT=ContextAPI.get_current_context()
HOST_URL=ContextAPI.inspect_context(name=CURRENT_CONTEXT.name)["Endpoints"]["docker"]["Host"]

class DockerManager:
    NETWORK: str = "garfield"

    def __init__(self):
        self.client: DockerClient = DockerClient(base_url=HOST_URL)
        if not (networks:=self.client.networks.list(names=[self.NETWORK])):
            raise ValueError("No active networks found!")
        self.network_id: str = networks[0].id
        self.network: DockerNetwork = self.client.networks.get(self.network_id)

    @property
    def containers(self) -> dict[str, DockerContainer]:
        return {container.name: container for container in self.network.containers}

    def container_info(self, name: str) -> ContainerState:
        try:
            container = self.containers[name]
        except KeyError as exc:
            active ="\n\t- " + "\n\t- ".join(self.containers.keys())
            raise ValueError(
                f"No container with name '{name}'.\nActive containers are:{active}"
            ) from exc
        return ContainerState.from_attrs(container.attrs)

if __name__ == "__main__":
    manager = DockerManager()
    print(manager.container_info("hj").uptime)