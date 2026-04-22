"""
Agent Core 模块

导出主要的Agent和Team接口
"""

# Agent
from agent.core.agent import (
    create_agent,
    create_simple_agent,
    simple_decode,
)

# Team
from agent.core.team import (
    create_data_mapping_team,
    get_team_instance,
    create_field_mapping_agent,
    create_threat_agent,
    create_enum_agent,
)

from agent.core.team_web import (
    get_team_manager,
    run_team_task,
    TeamManager,
)

__all__ = [
    # Agent
    "create_agent",
    "create_simple_agent",
    "simple_decode",
    # Team
    "create_data_mapping_team",
    "get_team_instance",
    "create_field_mapping_agent",
    "create_threat_agent",
    "create_enum_agent",
    "get_team_manager",
    "run_team_task",
    "TeamManager",
]
