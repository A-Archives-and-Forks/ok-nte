import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Generator, List, Optional, Tuple, Type, TypeVar

from ok import CannotFindException, TaskDisabledException, find_color_rectangles
from qfluentwidgets import FluentIcon

from src import text_white_color
from src.Labels import Labels
from src.tasks.AnomalyHunter import AnomalyHunter
from src.tasks.AnomalyTask import AnomalyTask
from src.tasks.BaseNTETask import BaseNTETask
from src.tasks.daily.CinemaDateTask import CinemaDateTask
from src.tasks.daily.CoffeeTask import CoffeeTask
from src.tasks.daily.DailyConfig import (
    DailyConfigSchema,
    DailyConfigurable,
    NamespacedConfigView,
    register_composed_config_i18n,
)
from src.tasks.daily.DailyConfigMigrator import DailyConfigMigrator
from src.tasks.daily.FountainTask import FountainTask
from src.tasks.daily.FurnitureTask import FurnitureTask
from src.tasks.daily.GiftTask import GiftTask
from src.tasks.NTEOneTimeTask import NTEOneTimeTask
from src.utils import image_utils as iu

WorkingTaskT = TypeVar("WorkingTaskT", bound=BaseNTETask)


@dataclass(frozen=True)
class DailyChildSpec:
    """One Daily-owned task and the behavior that differs from the default runner."""

    task_type: Type[BaseNTETask]
    after_success: Callable[[BaseNTETask], None] | None = None


class DailyTask(NTEOneTimeTask, BaseNTETask):
    """日常任务执行器"""

    # --- 配置项键名 ---
    CONF_TASK = "副本类型"
    TASK_NONE = "不执行"
    # NAME is both the visible task name and the persisted Daily configuration namespace.
    STAMINA_TASKS = [
        DailyChildSpec(AnomalyTask, after_success=lambda task: task.shift_id()),
        DailyChildSpec(AnomalyHunter),
    ]
    NORMAL_TASKS = [
        DailyChildSpec(CinemaDateTask),
        DailyChildSpec(FountainTask),
        DailyChildSpec(FurnitureTask),
        DailyChildSpec(GiftTask),
    ]
    DAILY_CHILD_TASKS = [*STAMINA_TASKS, *NORMAL_TASKS]

    CONF_CLAIM_MAIL = "领取邮件"
    CONF_COMPLETE_DAILY = "完成每日活跃度"
    CONF_CLAIM_ACTIVITY = "领取活跃度奖励"
    CONF_CLAIM_BP = "领取环期任务奖励"
    CONF_COFFEE_TASK = "一咖舍任务"
    DAILY_STAMINA_TARGET = "目标消耗体力"

    # --- 一咖舍任务选项 ---
    COFFEE_MODE_CLAIM_AND_RESTOCK = "领取/补货一咖舍"
    COFFEE_MODE_AUTO = "运行一咖舍自动化"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "日常任务"
        self.icon = FluentIcon.CAR
        self.group_name = "日常/周常"
        self.group_icon = FluentIcon.CALENDAR
        self.support_schedule_task = True
        self.task_status = {"success": [], "failed": [], "skipped": [], "pending": []}
        self.working_task: Optional["BaseNTETask"] = None
        self._daily_config_schemas: dict[str, DailyConfigSchema] = {}

        stamina_tasks_name = [self.TASK_NONE, *(spec.task_type.NAME for spec in self.STAMINA_TASKS)]

        self.default_config.update(
            {
                self.CONF_TASK: stamina_tasks_name[1],
                self.DAILY_STAMINA_TARGET: 180,
                self.CONF_COFFEE_TASK: self.TASK_NONE,
            }
        )
        self.config_description.update(
            {
                self.CONF_COFFEE_TASK: "选择日常任务中的一咖舍处理方式",
            }
        )
        coffee_options = [self.TASK_NONE, self.COFFEE_MODE_CLAIM_AND_RESTOCK]
        # 一咖舍自动化页面 OCR 仅匹配简体中文; 在非 zh_CN 下不向用户暴露自动化选项.
        if self.get_app_locale() == "zh_CN":
            coffee_options.append(self.COFFEE_MODE_AUTO)
        self.config_type.update(
            {
                self.CONF_TASK: {
                    "type": "drop_down",
                    "options": stamina_tasks_name,
                    "sub_configs": {},
                },
                self.CONF_COFFEE_TASK: {
                    "type": "drop_down",
                    "options": coffee_options,
                },
            }
        )
        self._build_tasks_config()

        self.current_task_key = None
        self.add_exit_after_config()

    def _build_tasks_config(self):
        schemas = []
        names = set()
        for spec in self.DAILY_CHILD_TASKS:
            task: Type[DailyConfigurable] = spec.task_type
            if task.NAME in names:
                raise ValueError(f"Daily child task name must be unique: {task.NAME}")
            names.add(task.NAME)
            schema = DailyConfigSchema(task.NAME)
            task.setup_config(schema, daily=True)
            self._daily_config_schemas[task.NAME] = schema
            schemas.append(schema)

        register_composed_config_i18n(schemas)
        top_level_configs = {schema.task_name: schema.install(self) for schema in schemas}
        stamina_sub_configs = self.config_type[self.CONF_TASK]["sub_configs"]
        for spec in self.STAMINA_TASKS:
            task = spec.task_type
            stamina_sub_configs[task.NAME] = [
                *top_level_configs[task.NAME],
                self.DAILY_STAMINA_TARGET,
            ]

        for spec in self.NORMAL_TASKS:
            task = spec.task_type
            self.default_config[task.NAME] = False
            if top_level_configs[task.NAME]:
                self.config_type[task.NAME] = {
                    "sub_configs": {True: top_level_configs[task.NAME]},
                }

    def load_config(self):
        DailyConfigMigrator(self).migrate()
        super().load_config()

    def run(self):
        super().run()
        try:
            self.do_run()
        except TaskDisabledException:
            pass
        except Exception as e:
            self._handle_exception(e)

    def do_run(self):
        """执行日常任务主流程"""
        self.scene.set_logged_in(False)
        self.ensure_main()
        self.log_info("开始执行日常任务")

        tasks: List[Tuple[str, bool, Callable]] = [
            (
                self.CONF_CLAIM_MAIL,
                self._task_enabled(self.CONF_CLAIM_MAIL, True),
                self.claim_mail,
            ),
            (
                self.CONF_COMPLETE_DAILY,
                self._task_enabled(self.CONF_COMPLETE_DAILY, True),
                self.complete_daily_activities,
            ),
            (
                self.CONF_COFFEE_TASK,
                self._task_enabled(self.CONF_COFFEE_TASK, self.TASK_NONE, self.TASK_NONE),
                self.run_coffee_task,
            ),
            (
                self.CONF_CLAIM_ACTIVITY,
                self._task_enabled(self.CONF_CLAIM_ACTIVITY, True),
                self.claim_activity_rewards,
            ),
            (
                self.CONF_CLAIM_BP,
                self._task_enabled(self.CONF_CLAIM_BP, True),
                self.claim_battle_pass_rewards,
            ),
        ]
        tasks.extend(
            (
                spec.task_type.NAME,
                self._task_enabled(spec.task_type.NAME, False),
                lambda spec=spec: self.run_daily_child(spec),
            )
            for spec in self.NORMAL_TASKS
        )

        self._reset_task_status(tasks)

        for task in tasks:
            self.execute_task(*task)

        self.ensure_main()
        self._print_result()
        self.log_info("结束执行日常任务", notify=True)

    def _task_enabled(self, key, default, not_equal=None):
        value = self.config.get(key, default)
        if isinstance(value, bool):
            return value
        elif not_equal and value != not_equal:
            return True
        return False

    def execute_task(self, key, enabled, func):
        """执行单个子任务。

        Args:
            key (str): 任务名称
            enabled (bool): 是否执行
            func (Callable): 任务执行函数

        根据配置决定是否跳过，并记录执行结果。
        """

        self.task_status["pending"].remove(key)

        if not enabled:
            self.task_status["skipped"].append(key)
            return

        self.current_task_key = key
        self.log_info(f"开始任务: {key}")

        self.ensure_main()

        try:
            result = func()
        except TaskDisabledException:
            raise
        except Exception as e:
            self.log_error(f"任务: {key} 运行失败", e)
            result = False

        if result is False:
            self.task_status["failed"].append(key)
            self.screenshot(f"fail_{key}")
            self.log_info(f"任务失败: {key}")
            return

        self.task_status["success"].append(key)
        self.log_info(f"任务完成: {key}")
        self.current_task_key = None

    def _reset_task_status(self, tasks):
        """重置任务状态。

        Args:
            tasks (list): [(key, func)] 任务列表
        """
        self.task_status = {
            "success": [],
            "failed": [],
            "skipped": [],
            "pending": [t[0] for t in tasks],
        }

    def _print_result(self):
        """输出任务执行结果。"""
        self.info_set("success", f"{self.task_status['success']}")
        self.info_set("failed", f"{self.task_status['failed']}")
        self.info_set("skipped", f"{self.task_status['skipped']}")

    def _handle_exception(self, e):
        """处理执行异常并记录状态。

        Args:
            e (Exception): 捕获到的异常
        """
        self.screenshot(f"{datetime.now().strftime('%Y%m%d')}_exception")

        if self.current_task_key:
            self.info_set("当前失败任务", self.current_task_key)
        self._print_result()
        raise e

    def _open_mail_panel(self):
        """打开mail panel。

        Returns:
            bool: True 表示成功，False 表示失败
        """

        def action():
            self.openESCpanel()
            self.operate_click(0.8707, 0.8736)
            self.sleep(0.5)
            return self.wait_panel(Labels.mail_panel)

        self.log_info("正在打开邮件面板")
        result = self.retry_on_action(action, self.ensure_main)
        if not result:
            self.log_error("无法找到邮件面板", notify=True)
            raise CannotFindException("can't find mail panel")
        return result

    def claim_mail(self):
        """领取邮件"""
        self.log_info("正在领取邮件奖励")
        self._open_mail_panel()
        self.operate_click(0.1289, 0.9299)
        self.sleep(1)
        return True

    def run_coffee_task(self):
        mode = self.config.get(self.CONF_COFFEE_TASK)
        match mode:
            case self.COFFEE_MODE_AUTO:
                with self.set_registered_working_task(CoffeeTask) as task:
                    return task.do_run()
            case self.COFFEE_MODE_CLAIM_AND_RESTOCK:
                return self.claim_coffee()
        return True

    def complete_daily_activities(self):
        """执行操作完成每日活跃度"""
        self.log_info("正在执行每日活跃度任务")
        if self.check_activity():
            self.log_info("当前体力消耗或每日活跃度已达标，跳过每日活跃度任务")
            return True

        used_stamina = self.info_get("used stamina")
        target_stamina = self.config.get(self.DAILY_STAMINA_TARGET, 180)
        must_use = target_stamina - used_stamina
        if must_use <= 0:
            self.log_info(
                f"当前体力消耗: {used_stamina}, {self.DAILY_STAMINA_TARGET}: {target_stamina}"
            )
            self.log_info("目标已达成，跳过每日活跃度任务")
            return True
        self.info_set("must use stamina", must_use)

        task_name = self.config.get(self.CONF_TASK)
        spec = next((spec for spec in self.STAMINA_TASKS if spec.task_type.NAME == task_name), None)
        if spec is None:
            return False
        with self.set_working_task(spec.task_type) as task:
            result = task.do_run(stamina_target=must_use)
            if result and spec.after_success:
                spec.after_success(task)
            return result

    @contextmanager
    def set_working_task(self, cls: Type[WorkingTaskT]) -> Generator[WorkingTaskT, None, None]:
        schema = self._daily_config_schemas[cls.NAME]
        working_task = cls(executor=self.executor, app=self._app)
        config = NamespacedConfigView(
            self.config,
            schema.task_name,
            schema.config_keys,
            schema.runtime_keys,
        )
        working_task.prepare_for_daily(config=config, scene=self.scene, info=self.info)
        with self._activate_working_task(working_task):
            yield working_task

    @contextmanager
    def set_registered_working_task(
        self, cls: Type[WorkingTaskT]
    ) -> Generator[WorkingTaskT, None, None]:
        working_task = self.get_task_by_class(cls)
        if working_task is None:
            raise RuntimeError(f"Registered daily task is unavailable: {cls.__name__}")
        with self._activate_working_task(working_task):
            yield working_task

    @contextmanager
    def _activate_working_task(
        self, working_task: WorkingTaskT
    ) -> Generator[WorkingTaskT, None, None]:
        old_working_task = self.working_task
        old_sleep_check_interval = self.sleep_check_interval
        old_task_info = working_task.info
        self.working_task = working_task
        working_task.info = self.info
        self.sleep_check_interval = working_task.sleep_check_interval
        try:
            yield working_task
        finally:
            working_task.info = old_task_info
            self.working_task = old_working_task
            self.sleep_check_interval = old_sleep_check_interval

    def sleep_check(self):
        if self.working_task:
            return self.working_task.sleep_check()
        return super().sleep_check()

    def _open_activity(self):
        def action():
            self.openF1panel()
            self.operate_click(0.0551, 0.3833)
            self.sleep(0.5)
            return self.wait_panel(Labels.f1_activity_panel)

        self.log_info("开启活跃度面板")
        result = self.retry_on_action(action, self.ensure_main)
        if not result:
            self.log_error("无法找到活跃度面板")
            return False
        return True

    def check_activity(self):
        if not self._open_activity():
            return False
        activity_re = re.compile(r"(\d+)")
        mission_re = re.compile(r"^(\d+)/180$")
        used_stamina = 0
        daily_activity = 0

        mission_box = self.box_of_screen(0.184, 0.652, 0.781, 0.710, name="mission", hcenter=True)
        activity_box = self.box_of_screen(0.184, 0.188, 0.256, 0.255, name="activity", hcenter=True)

        activity = self.ocr(box=activity_box, match=activity_re)

        for _ in range(2):
            mission = self.ocr(box=mission_box, match=mission_re)

            if mission:
                match = mission_re.search(mission[0].name)
                if match:
                    used_stamina = int(match.group(1))
                    self.log_info(f"ocr found used stamina {used_stamina}")
                    break
            else:
                self.operate(
                    lambda: self.scroll_relative(0.2379, 0.7285, -42),
                    block=True,
                )
                self.sleep(0.25)

        if activity:
            match = activity_re.search(activity[0].name)
            if match:
                daily_activity = int(match.group(1))
                self.log_info(f"ocr found daily activity {daily_activity}")

        self.info_set("used stamina", used_stamina)
        self.info_set("daily activity", daily_activity)

        return used_stamina >= 180 or daily_activity >= 100

    def claim_activity_rewards(self, in_panel=False):
        """领取活跃度奖励"""
        self.log_info("正在领取活跃度奖励")
        if not in_panel and not self._open_activity():
            return False
        if self.find_one(Labels.f1_activity_mission):
            self.operate_click(0.2348, 0.7653)
            self.sleep(2)

        if target := self._get_activity_reward_box():
            self.wait_until(
                lambda: not self._get_activity_reward_box(),
                pre_action=lambda: self.operate_click(target, interval=1),
            )
            self.sleep(1)
        else:
            self.log_error("无法找到活跃度奖励领取框")
            return False
        return True

    def _get_activity_reward_box(self):
        target = None
        box = self.get_box_by_name(Labels.box_f1_activity_reward)
        mask = iu.binarize_bgr_by_brightness(self.frame, threshold=245, to_bgr=False)
        mask = iu.morphology_mask(mask, kernel_size=7, to_bgr=True)
        reward_boxes = find_color_rectangles(
            mask, color_range=text_white_color, min_width=10, min_height=10, box=box, threshold=0.6
        )
        if reward_boxes:
            target = max(reward_boxes, key=lambda x: x.x)
            self.draw_boxes(boxes=target)
        return target

    def claim_battle_pass_rewards(self):
        """领取环期任务奖励"""

        def action():
            self.openF2panel()
            self.operate_click(0.0570, 0.3451)
            self.sleep(0.5)
            return self.wait_panel(Labels.f2_mission_panel)

        self.log_info("正在领取环期任务奖励")
        result = self.retry_on_action(action, self.ensure_main)
        if not result:
            self.log_error("无法找到环期任务面板")
            return False
        self.operate_click(0.8777, 0.8187)
        self.sleep(1)
        self.operate_click(0.0570, 0.2333)
        self.sleep(1)
        self.operate_click(0.6934, 0.8229)
        self.sleep(1)
        return True

    def claim_coffee(self):
        """领取一咖舍奖励"""

        def action():
            self.openF5panel()
            self.operate_click(0.415, 0.753)
            self.sleep(0.5)
            return self.wait_panel(Labels.f5_coffee_panel)

        self.log_info("正在领取一咖舍奖励")
        result = self.retry_on_action(action, self.ensure_main)
        if not result:
            self.log_error("无法找到一咖舍面板")
            return False
        self.sleep(1)

        # 提取收益
        self.wait_until(
            lambda: not self.find_one(Labels.f5_coffee_panel),
            pre_action=lambda: self.operate_click(0.188, 0.877, interval=1),
            time_out=10,
        )
        self.sleep(1)
        self.wait_until(
            lambda: self.find_one(Labels.f5_coffee_panel),
            pre_action=lambda: self.operate_click(0.072, 0.886, interval=1),
            time_out=10,
            settle_time=0.5,
        )
        self.sleep(1)

        # 进入补货
        self.wait_until(
            lambda: not self.find_one(Labels.f5_coffee_panel),
            pre_action=lambda: self.operate_click(0.115, 0.530, interval=1),
            time_out=10,
            settle_time=0.5,
        )
        self.sleep(1)

        # 补货
        self.operate_click(0.340, 0.785)  # 24hr
        self.sleep(1)
        self.operate_click(0.717, 0.787)  # 补货
        self.sleep(1)
        self.operate_click(0.595, 0.776)  # 送货上门
        self.sleep(1)
        self.operate_click(0.600, 0.656)  # 确认
        return True

    def run_daily_child(self, spec: DailyChildSpec):
        with self.set_working_task(spec.task_type) as task:
            return task.do_run()
