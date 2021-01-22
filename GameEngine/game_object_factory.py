from _py_abc import ABCMeta
import json
import sys
from typing import Callable

import pygame


class GameObjectBase(metaclass=ABCMeta):
    """Base class for GameObject."""

    __next_object_id = 0

    def __str__(self):
        return "{0}: {1}".format(self.__object_id, super().__str__())

    def set_object_id(self):
        """
        Sets the object id. This is meant to aid debugging and should only be set once (when GameObjectFactory
        creates the object.
        """
        self.__object_id = GameObjectBase.__next_object_id
        GameObjectBase.__next_object_id += 1

    def get_object_id(self):
        return self.__object_id


class GameObjectFactory():
    """
    GameObject factory.

    The following article helped a lot on the details of the implementation of GameObjectFactory:
    https://medium.com/@geoffreykoh/implementing-the-factory-pattern-via-dynamic-registry-and-python-decorators-479fc1537bbe
    """

    class UnknownGameType(Exception):
        """Exception raised when trying to instantiate an unknown GameObject class."""

        def __init__(self, message):
            super().__init__(message)

    registry = {}
    surfaces = {}
    sounds = {}
    game_types = {}
    assets = {}
    layer_manager = None

    __asset_json_objects = []

    @classmethod
    def initialize(cls, inventory_fp):
        data = json.load(inventory_fp, object_hook=GameObjectFactory.__json_object_hook)

        # Load surfaces
        cls.surfaces = {}
        data_images = data["surfaces"]
        for key in data_images.keys():
            cls.surfaces[key] = pygame.image.load(data_images[key]).convert_alpha()

        # Load sounds
        cls.sounds = {}
        data_sounds = data["sounds"]
        for key in data_sounds.keys():
            cls.sounds[key] = pygame.mixer.Sound(data_sounds[key])

        # Assets and game_types can be assigned directly
        cls.game_types = data["game_types"]

        # Initialize assets with surfaces and the corresponding asset object
        cls.assets = data["assets"]

        # Create asset objects
        for key in cls.assets.keys():
            asset_spec = cls.assets[key]
            asset_spec["asset"] = GameObjectFactory.__create_object(asset_spec, "")

        # Assign initialized assets to the fields that reference them
        for obj, key in cls.__asset_json_objects:
            asset_name = obj[key]
            if isinstance(asset_name, str):
                obj[key[len("asset:"):]] = cls.assets[asset_name]["asset"]
            elif isinstance(asset_name, list):
                inner_key = key[len("asset:"):]
                obj[inner_key] = []
                asset_list = obj[inner_key]
                cls.__assign_asset_list(asset_name, asset_list)
            del obj[key]
        del cls.__asset_json_objects

        # Initialize layer manager if there is one
        layer_manager_spec = cls.assets.get("LayerManager")
        if layer_manager_spec:
            cls.layer_manager = layer_manager_spec["asset"]
        else:
            sys.stderr.write("GameObjectFactory: No LayerManager defined in inventory assets.\n")

    @classmethod
    def create(cls, name: str, scope="", **kwargs) -> GameObjectBase:
        """Creates a GameObject instance."""
        scoped_name = name
        if name[0] != '/':
            scoped_name = "/".join([scope, name])

        game_type = GameObjectFactory.__get_game_type(scoped_name)
        gob = GameObjectFactory.__create_object(game_type, scoped_name, **kwargs)

        # Add to groups as specified in type spec
        group_names = game_type.get("groups")
        if group_names:
            if "RenderGroup" in group_names:
                # Get layer id for the GameObject only if it's in the RenderGroup
                layer_id = LayerManager.invalid_layer_id
                if cls.layer_manager != None:
                    layer_id = cls.layer_manager.get_layer_id(name)
                    if layer_id == cls.layer_manager.invalid_layer_id:
                        layer_id = cls.layer_manager.get_layer_id(game_type["class_name"])

                # name not found in known layers
                if layer_id != LayerManager.invalid_layer_id:
                    gob.set_layer_id(layer_id)
                else:
                    sys.stderr.write("Game type name '{0}' doesn't have an assigned layer in LayerManager.\n".format(
                        name
                    ))
            groups = [cls.assets[name]["asset"] for name in group_names]
            gob.add_to_groups(groups)

        # Create attachments
        attachment_specs = game_type.get("attachments")
        if gob and attachment_specs:
            for attachment_spec in attachment_specs:
                attachment_object = GameObjectFactory.create(attachment_spec["game_type"], scoped_name)
                if attachment_object:
                    parent_transform = attachment_spec.get("parent_transform")
                    if parent_transform == None:
                        parent_transform = True
                    gob.attach(attachment_object, attachment_spec["offset"], parent_transform)
                    gob.transform()

        return gob

    @classmethod
    def get_asset(cls, name: str) -> GameObjectBase:
        """Returns an initialized asset."""
        asset_spec = cls.assets[name]
        if asset_spec:
            return asset_spec["asset"]
        else:
            sys.stderr.write("Asset {0} does not exist.\n".format(name))
            return None

    @classmethod
    def __get_game_type(cls, name: str) -> dict:
        """Gets the given game type, recursing into nested dictionaries as necessary."""
        keys = name.lstrip('/').split('/')
        game_type = cls.game_types
        while len(keys) > 0:
            try:
                for key in keys:
                    game_type = game_type[key]
                return game_type
            except KeyError:
                del keys[0]
                game_type = cls.game_types
        raise GameObjectFactory.UnknownGameType("".join(["Unknown game type: ", name]))

    @classmethod
    def __create_object(cls, type_spec, scope, **kwargs) -> GameObjectBase:
        # Assemble new game type dictionary with resolved "image:", "image_list:", and "game_object_type:" fields
        resolved_refs = {}
        type_spec_kwargs = type_spec["kwargs"]
        for key in type_spec_kwargs:
            if key.startswith("image:"):
                image_name = type_spec_kwargs[key]
                resolved_refs[key[len("image:"):]] = cls.surfaces[image_name]
            elif key.startswith("image_list:"):
                image_list = type_spec_kwargs[key]
                resolved_refs[key[len("image_list:"):]] = [cls.surfaces[image_str] for image_str in image_list]
            elif key.startswith("sound:"):
                sound_name = type_spec_kwargs[key]
                resolved_refs[key[len("sound:"):]] = cls.sounds[sound_name]
            elif key.startswith("game_object_type:"):
                gob_type_name = type_spec_kwargs[key]
                resolved_refs[key[len("type_spec_object:"):]] = GameObjectFactory.create(gob_type_name, scope)
            elif key.startswith("game_object_type_list:"):
                gob_type_list = type_spec_kwargs[key]
                resolved_refs[key[len("game_object_type_list:"):]] = [
                    GameObjectFactory.create(gob_type_name, scope) for gob_type_name in gob_type_list
                ]
            else:
                resolved_refs[key] = type_spec_kwargs[key]

        try:
            gob_class = cls.registry[type_spec["class_name"]]
            gob = gob_class(**resolved_refs, **kwargs)
            gob.set_object_id()
            return gob
        except KeyError:
            sys.stderr.write("GameObjectBase subclass '{0}' not found.\n".format(type_spec["class_name"]))
            return None

    @classmethod
    def __json_object_hook(cls, obj_dict):
        """Keeps track of JSON objects (dictionaries) that will have to be initialized further."""
        for key in obj_dict.keys():
            if key.startswith("asset:"):
                cls.__asset_json_objects.append((obj_dict, key))
            elif key.startswith("asset_list:"):
                cls.__asset_list_json_objects.append((obj_dict, key))
        return obj_dict

    @classmethod
    def __assign_asset_list(cls, asset_names, asset_list):
        """
        Goes into asset_list and assigns the initialized assets to the right asset spec elements in the assets
        dictionary. This enables support for nested lists of assets in the asset specs. See the CollisionManager
        for an example of a GameObject that relies on this.
        """
        for asset_name in asset_names:
            if isinstance(asset_name, str):
                asset_list.append(cls.assets[asset_name]["asset"])
            else:
                asset_list.append([])
                cls.__assign_asset_list(asset_name, asset_list[-1])

    @classmethod
    def register(cls, name: str) -> Callable:
        """Registers a new GameObject child class."""

        def inner_wrapper(wrapped_class: GameObjectBase) -> Callable:
            if name in cls.registry:
                sys.stderr.write("Class '{0}' already registered. Overwriting old value.".format(name))
            cls.registry[name] = wrapped_class
            return wrapped_class

        return inner_wrapper


@GameObjectFactory.register("LayerManager")
class LayerManager(GameObjectBase):
    """
    Manages draw layers semi-automatically.

    The order of GameObject subclasses defined in self.layers determines the draw order. Abstract game types
    declared in the inventory file can also be used in self.layers.

    GameObjectFactory sets the 'layer' constructor argument in every GameObject instance it creates. The value of
    the parameter comes from the object's class or abstract game type, as defined in LayerManager's 'layers' list.
    """

    invalid_layer_id = -1

    def __init__(self, layers):
        self.layers = layers

    def get_layer_id(self, name):
        """Returns the layer for the given game type name."""
        for index, layer in enumerate(self.layers):
            if name in layer:
                return index
        return self.invalid_layer_id
