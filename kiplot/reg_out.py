from .optionable import Optionable


class RegOutput(Optionable):
    """ This class adds the mechanism to register outputs """
    _registered = {}

    def __init__(self):
        super().__init__()

    @staticmethod
    def register(name, aclass):
        RegOutput._registered[name] = aclass

    @staticmethod
    def is_registered(name):
        return name in RegOutput._registered

    @staticmethod
    def get_class_for(name):
        return RegOutput._registered[name]

    @staticmethod
    def get_registered():
        return RegOutput._registered
