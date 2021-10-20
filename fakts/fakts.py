from typing import List
from koil import koil
import yaml
from fakts.grants.base import FaktsGrant
import os
from fakts.grants.yaml import YamlGrant
import logging


logger = logging.getLogger(__name__)

class Fakts:

    def __init__(self, *args, grants = [YamlGrant(filepath="bergen.yaml")], save_conf="bergen.yaml", register= True, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.loaded = False
        self.grants: List[FaktsGrant] = grants
        assert len(self.grants) > 0, "Please provide allowed Grants to retrieve the Konfiguration from"
        self.fakts = {}
        self.failedResponses = {}

        self.save_conf = save_conf
        if self.save_conf:
            try:
                self.fakts = self.load_config_from_file()
                self.loaded = True
            except:
                logger.info(f"Couldn't load local conf-file {save_conf}. We will have to refetch!")

        if register:
            set_current_fakts(self)

    
    def load_config_from_file(self, filepath = None):
        with open(filepath or self.save_conf,"r") as file:
            return yaml.load(file, Loader=yaml.FullLoader)


    def load_group(self, group_name):
        assert self.loaded, "Konfik needs to be loaded before we can access call load()"
        config = self.fakts
        for subgroup in group_name.split("."):
            try:
                config = config[subgroup]
            except KeyError as e:
                print(f"Could't find {subgroup} in {config}")
                config = {}
        return config


    async def arefresh(self):
        await self.aload()

    async def aload(self):
        for grant in self.grants:
            try:
                self.fakts = await grant.aload()
                break
            except Exception as e:
                self.failedResponses[grant.__class__.__name__] = e

        assert self.fakts, f"We did not received any valid Responses from our Grants. {self.failedResponses}"

        if self.save_conf:
            with open(self.save_conf,"w") as file:
                yaml.dump(self.fakts, file)

        self.loaded = True

    async def adelete(self):
        self.loaded = False
        self.fakts = None

        if self.save_conf:
            os.remove(self.save_conf)

    def load(self):
        return koil(self.aload())

    def delete(self):
        return koil(self.adelete())
















CURRENT_FAKTS = None

def get_current_fakts(**kwargs) -> Fakts:
    global CURRENT_FAKTS
    if not CURRENT_FAKTS:
        CURRENT_FAKTS = Fakts(**kwargs)
    return CURRENT_FAKTS

def set_current_fakts(fakts) -> Fakts:
    global CURRENT_FAKTS
    if CURRENT_FAKTS: print("Hmm there was another fakts set, maybe thats cool but more likely not")
    CURRENT_FAKTS = fakts
