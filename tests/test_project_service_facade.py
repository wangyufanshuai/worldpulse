from app.services import projects
from app.services.project_app import repository
from app.services.project_app import service


def test_projects_module_remains_public_facade():
    assert callable(projects.run_project)
    assert callable(projects.chat_with_project)
    assert projects.run_project_war_room is service.run_project_war_room
    assert projects.persist_war_room_result is service.persist_war_room_result
    assert projects.war_room_workspace is service.war_room_workspace
    assert projects.compare_project_runs is service.compare_project_runs
    assert projects.war_room_replay_pack is service.war_room_replay_pack


def test_project_repository_owns_row_mapping_helpers():
    assert callable(repository.get_project)
    assert callable(repository.project_runs)
    assert callable(repository.run_by_id)
    assert callable(repository.latest_graph)
    assert callable(repository.report_for_run)
