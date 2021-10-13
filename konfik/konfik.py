from typing import List
from koil import koil
import yaml
from konfik.grants.base import KonfigGrant
import os
from konfik.grants.yaml import YamlGrant
import logging


logger = logging.getLogger(__name__)

class Konfik:

    def __init__(self, *args, grants = [YamlGrant(filepath="bergen.yaml")], save_conf="bergen.yaml", register= True, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.loaded = False
        self.grants: List[KonfigGrant] = grants
        assert len(self.grants) > 0, "Please provide allowed Grants to retrieve the Konfiguration from"
        self.konfig_dict = {}
        self.grantResponse = None
        self.failedResponses = []

        self.save_conf = save_conf
        if self.save_conf:
            try:
                self.konfig_dict = self.load_config_from_file()
                self.loaded = True
            except:
                logger.info(f"Couldn't load local conf-file {save_conf}. We will have to refetch!")

        if register:
            set_current_konfik(self)

    
    def load_config_from_file(self, filepath = None):
        with open(filepath or self.save_conf,"r") as file:
            return yaml.load(file, Loader=yaml.FullLoader)


    def load_group(self, group_name):
        assert self.loaded, "Konfik needs to be loaded before we can access call load()"
        config = self.konfig_dict
        for subgroup in group_name.split("."):
            try:
                config = config[subgroup]
            except KeyError as e:
                print(f"Could't find {subgroup} in {config}")
                config = {}
        return config


    async def arefresh(self):
        if self.save_conf:
            with open(self.save_conf,"w") as file:
                yaml.dump(self.grantResponse, file)

    async def aload(self):
        for grant in self.grants:
            try:
                self.grantResponse = await grant.aload()
                break
            except Exception as e:
                self.failedResponses.append(f"{grant.__class__.__name__} failed with {e}")

        assert self.grantResponse, f"We did not received any valid Responses from our Grants. {self.failedResponses}"

        if self.save_conf:
            with open(self.save_conf,"w") as file:
                yaml.dump(self.grantResponse, file)


        self.loaded = True
        self.konfig_dict = self.grantResponse

    async def adelete(self):
        self.grantResponse = None
        self.loaded = False
        self.konfig_dict = self.grantResponse

        if self.save_conf:
            os.remove(self.save_conf)

    def load(self):
        return koil(self.aload())

    def delete(self):
        return koil(self.adelete())
















CURRENT_KONFIK = None

def get_current_konfik(**kwargs) -> Konfik:
    global CURRENT_KONFIK
    if not CURRENT_KONFIK:
        CURRENT_KONFIK = Konfik(**kwargs)
    return CURRENT_KONFIK

def set_current_konfik(konfik) -> Konfik:
    global CURRENT_KONFIK
    if CURRENT_KONFIK: print("Hmm there was another konfik set, maybe thats cool but more likely not")
    CURRENT_KONFIK = konfik
