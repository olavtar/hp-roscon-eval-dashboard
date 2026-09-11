from eval_dashboard.web.app import create_app


class EpisodeStore:
    def __init__(self, episodes):
        self._episodes = episodes

    def episodes(self):
        return list(self._episodes)

    def snapshot(self):
        return {}


def test_episode_api_pages_the_selected_policy_union_in_time_order():
    store = EpisodeStore(
        [
            {"episode_id": "old-a", "model_version": "a", "timestamp": "2026-09-01T00:00:00Z"},
            {"episode_id": "new-b", "model_version": "b", "timestamp": "2026-09-04T00:00:00Z"},
            {"episode_id": "middle-a", "model_version": "a", "timestamp": "2026-09-03T00:00:00Z"},
            {"episode_id": "other", "model_version": "other", "timestamp": "2026-09-05T00:00:00Z"},
        ]
    )
    client = create_app(store, "files").test_client()

    response = client.get("/api/episodes?model_version=a&model_version=b&limit=1&offset=1")

    assert response.status_code == 200
    assert [row["episode_id"] for row in response.get_json()] == ["middle-a"]


def test_episode_api_rejects_non_numeric_pagination():
    client = create_app(EpisodeStore([]), "files").test_client()

    response = client.get("/api/episodes?limit=many")

    assert response.status_code == 400
