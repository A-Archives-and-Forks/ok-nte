import time

from src.char.BaseChar import BaseChar
from src.combat.planner import (
    ActionIntent,
    Planner,
    RoleProfile,
)


class Nanally(BaseChar):
    cn_name = "娜娜莉"
    element = BaseChar.Element.GREEN

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def describe_role(self):
        return RoleProfile(
            role=Planner.Role.MAIN_DPS,
            field_preference=Planner.FieldPreference.MAIN_DPS,
            max_field_time=1.5,
        )

    def combat_plan(self, context):
        skill = self.click_skill_action()
        ultimate = self.click_ultimate_action()

        def entry():
            skill_result = yield skill
            if skill_result and self.ultimate_available():
                self.sleep(0.6)

            ultimate_result = yield ultimate
            if ultimate_result:
                yield from self.perform_in_ult(skill)

        return self.plan(
            skill,
            ultimate,
            entry=entry,
        )

    def perform_in_ult(self, skill: "ActionIntent"):
        start = time.time()
        skill_used = False
        while (elapsed := time.time() - start) < 6:
            if elapsed > 1 and not self.ultimate_available(False):
                break
            if not skill_used:
                skill_used = bool((yield skill.repeat_for_entry()))
            self.normal_attack()
            self.sleep(0.2)
        return skill_used
    
    def on_combat_end(self, chars):
        self.switch_other_char()
