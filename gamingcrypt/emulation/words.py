"""Easy-to-type passwords for the upload page: two random English words ("BlueTiger")."""

from __future__ import annotations

import secrets

WORDS = """
able acid aged also arch area army atom aunt away baby back bake ball band bank barn base bath bead beam
bean bear beef bell belt bench berry bike bird blade blue boat body bone book boot bowl brain brave bread
brick bride brook brush bulb bunny cabin cake calm camel camp candy cape card cargo carpet castle cave chair
chalk charm cheek cheese cherry chess chief chip cider city clay cliff clock cloud clover coal coast coat
cocoa coin comet coral corn cotton couch cow crab crane crown cube cup daisy dance dawn deer desk dice diver
dock dog doll dome door dove dragon dream drum duck dune eagle earth easy echo eel egg elbow elder elk ember
fable fairy farm feast fern field film fire fish flag flame flute foam fog forest fox frog frost fruit gate
gecko gem ghost giant gift ginger glass globe glove goat gold goose grape grass gravel green grove guitar
hall hammer harbor harp hat hawk hazel heart hedge hero hill honey hoop horn horse hotel house ice igloo
island ivory ivy jacket jade jam jelly jewel judge juice jungle kayak kettle key king kite kiwi knight koala
lace ladder lake lamp lantern lava leaf lemon letter lilac lily lime lion lizard llama lobster lotus lucky
lunar magic mango maple marble market meadow melon metal milk mint mirror moon moose moss mouse muffin music
nest night noble north nut oak oasis ocean olive onion opal orange orbit otter owl palm panda paper parrot
pasta peach pearl pebble pencil pepper piano pilot pine pizza planet plum polar pond poppy pony prism puppy
quail queen quiet quill rabbit radar rain raven reef rice ring river robin rocket rose ruby saddle sail salt
sand saturn scarf seal shadow shell ship silk silver sky sled snow sock sofa solar spark spice spider spoon
spring star steam stone storm sugar summer sun swan table tango tea tiger timber toast tomato torch tower
train tree tulip tuna turtle valley velvet violet violin wagon walnut water wave whale wheat willow window
winter wizard wolf wood yarn yeti zebra
""".split()


MIN_LENGTH = 8  # the network share's helper takes no shorter password ("OakFox" made it fail)


def phrase(count: int = 2, min_length: int = MIN_LENGTH) -> str:
    """Words with a capital first letter each, e.g. "MapleOtter" - at least ``min_length`` long."""
    while True:
        text = "".join(secrets.choice(WORDS).capitalize() for _ in range(count))
        if len(text) >= min_length:
            return text
