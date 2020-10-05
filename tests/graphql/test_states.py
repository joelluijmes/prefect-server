import os

import pytest

from prefect import api, models
from prefect.engine.result import Result, SafeResult
from prefect.engine.result_handlers import JSONResultHandler
from prefect.engine.state import Retrying, Running, Submitted, Success


@pytest.fixture
async def locked_flow_run_id(flow_group_id, flow_run_id):
    await models.FlowGroup.where(id=flow_group_id).update(
        {"settings": {"version_locking_enabled": True}}
    )
    return flow_run_id


@pytest.fixture
async def locked_task_run_id(flow_group_id, task_run_id):
    await models.FlowGroup.where(id=flow_group_id).update(
        {"settings": {"version_locking_enabled": True}}
    )
    return task_run_id


class TestSetFlowRunStates:
    mutation = """
        mutation($input: set_flow_run_states_input!) {
            set_flow_run_states(input: $input) {
                states {
                    id
                    status
                    message
                }
            }
        }
    """

    async def test_set_flow_run_state(self, run_query, flow_run_id):
        result = await run_query(
            query=self.mutation,
            variables=dict(
                input=dict(
                    states=[dict(flow_run_id=flow_run_id, state=Running().serialize())]
                )
            ),
        )

        assert result.data.set_flow_run_states.states[0].id == flow_run_id
        assert result.data.set_flow_run_states.states[0].status == "SUCCESS"
        assert result.data.set_flow_run_states.states[0].message is None

        fr = await models.FlowRun.where(id=flow_run_id).first({"state", "version"})
        assert fr.version == 3
        assert fr.state == "Running"

    async def test_set_flow_run_state_with_version(self, run_query, flow_run_id):
        result = await run_query(
            query=self.mutation,
            variables=dict(
                input=dict(
                    states=[
                        dict(
                            flow_run_id=flow_run_id,
                            version=1,
                            state=Running().serialize(),
                        )
                    ]
                )
            ),
        )

        assert result.data.set_flow_run_states.states[0].id == flow_run_id
        assert result.data.set_flow_run_states.states[0].status == "SUCCESS"
        assert result.data.set_flow_run_states.states[0].message is None

        fr = await models.FlowRun.where(id=flow_run_id).first({"state", "version"})
        assert fr.version == 3
        assert fr.state == "Running"

    async def test_set_flow_run_state_with_bad_version(
        self, run_query, locked_flow_run_id
    ):
        result = await run_query(
            query=self.mutation,
            variables=dict(
                input=dict(
                    states=[
                        dict(
                            flow_run_id=locked_flow_run_id,
                            version=10,
                            state=Running().serialize(),
                        )
                    ]
                )
            ),
        )

        assert "State update failed" in result.errors[0].message

        fr = await models.FlowRun.where(id=locked_flow_run_id).first(
            {"state", "version"}
        )
        assert fr.version == 2
        assert fr.state == "Scheduled"

    async def test_set_multiple_flow_run_states(
        self, run_query, flow_run_id, flow_run_id_2, flow_run_id_3
    ):
        result = await run_query(
            query=self.mutation,
            variables=dict(
                input=dict(
                    states=[
                        dict(flow_run_id=flow_run_id, state=Running().serialize()),
                        dict(flow_run_id=flow_run_id_2, state=Success().serialize()),
                        dict(flow_run_id=flow_run_id_3, state=Retrying().serialize()),
                    ]
                )
            ),
        )
        assert result.data.set_flow_run_states.states == [
            {"id": flow_run_id, "status": "SUCCESS", "message": None},
            {"id": flow_run_id_2, "status": "SUCCESS", "message": None},
            {"id": flow_run_id_3, "status": "SUCCESS", "message": None},
        ]

        fr1 = await models.FlowRun.where(
            id=result.data.set_flow_run_states.states[0].id
        ).first({"state", "version"})
        assert fr1.version == 3
        assert fr1.state == "Running"

        fr2 = await models.FlowRun.where(
            id=result.data.set_flow_run_states.states[1].id
        ).first({"state", "version"})
        assert fr2.version == 4
        assert fr2.state == "Success"

        fr3 = await models.FlowRun.where(
            id=result.data.set_flow_run_states.states[2].id
        ).first({"state", "version"})
        assert fr3.version == 5
        assert fr3.state == "Retrying"

    async def test_set_multiple_flow_run_states_with_one_failed(
        self, run_query, locked_flow_run_id, flow_run_id_3
    ):
        result = await run_query(
            query=self.mutation,
            variables=dict(
                input=dict(
                    states=[
                        dict(
                            flow_run_id=locked_flow_run_id,
                            # BAD VERSION
                            version=100,
                            state=Success().serialize(),
                        ),
                        dict(
                            flow_run_id=flow_run_id_3,
                            version=4,
                            state=Retrying().serialize(),
                        ),
                    ]
                )
            ),
        )

        assert result.data.set_flow_run_states is None
        assert (
            f"State update failed for flow run ID {locked_flow_run_id}"
            in result.errors[0].message
        )

        # this update failed
        fr2 = await models.FlowRun.where(id=locked_flow_run_id).first(
            {"state", "version"}
        )
        assert fr2.version == 2
        assert fr2.state == "Scheduled"

    async def test_set_flow_run_state_with_result(self, run_query, flow_run_id):
        result = Result(10, result_handler=JSONResultHandler())
        result.store_safe_value()
        state = Success(result=result)

        result = await run_query(
            query=self.mutation,
            variables=dict(
                input=dict(
                    states=[dict(flow_run_id=flow_run_id, state=state.serialize())]
                )
            ),
        )
        fr = await models.FlowRun.where(
            id=result.data.set_flow_run_states.states[0].id
        ).first({"state", "version"})
        assert fr.version == 3
        assert fr.state == "Success"

    async def test_set_flow_run_state_with_saferesult(self, run_query, flow_run_id):
        result = SafeResult("10", result_handler=JSONResultHandler())
        state = Success(result=result)

        result = await run_query(
            query=self.mutation,
            variables=dict(
                input=dict(
                    states=[dict(flow_run_id=flow_run_id, state=state.serialize())]
                )
            ),
        )
        fr = await models.FlowRun.where(
            id=result.data.set_flow_run_states.states[0].id
        ).first({"state", "version"})
        assert fr.version == 3
        assert fr.state == "Success"

    async def test_set_flow_run_states_rejects_states_with_large_payloads(
        self, run_query, flow_run_id, flow_run_id_2
    ):
        result = await run_query(
            query=self.mutation,
            variables=dict(
                input=dict(
                    states=[
                        dict(
                            flow_run_id=flow_run_id,
                            # this state should successfully set
                            state=Running().serialize(),
                        ),
                        dict(
                            flow_run_id=flow_run_id_2,
                            # nonsense payload, just large
                            state={
                                i: os.urandom(2 * 1000000).decode("latin")
                                for i in range(2)
                            },
                        ),
                    ]
                )
            ),
        )
        assert "State payload is too large" in result.errors[0].message

    async def test_set_flow_run_states_coerced_to_queued(
        self,
        run_query,
        flow_id: str,
        flow_concurrency_limit: models.FlowConcurrencyLimit,
    ):
        flow_run_id = await api.runs.create_flow_run(
            flow_id, labels=[flow_concurrency_limit.name]
        )
        # Should succeed, taking first concurrency slot
        result = await run_query(
            query=self.mutation,
            variables=dict(
                input=dict(
                    states=[dict(flow_run_id=flow_run_id, state=Running().serialize())]
                )
            ),
        )

        assert result.data.set_flow_run_states.states[0].id == flow_run_id
        assert result.data.set_flow_run_states.states[0].status == "SUCCESS"
        assert result.data.set_flow_run_states.states[0].message is None

        fr = await models.FlowRun.where(id=flow_run_id).first({"state", "version"})
        assert fr.version == 3
        assert fr.state == "Running"

        # Should succeed, but get coerced to a `Queued` state
        second_run = await api.runs.create_flow_run(
            flow_id, labels=[flow_concurrency_limit.name]
        )
        result = await run_query(
            query=self.mutation,
            variables=dict(
                input=dict(
                    states=[dict(flow_run_id=second_run, state=Running().serialize())]
                )
            ),
        )

        assert result.data.set_flow_run_states.states[0].id == second_run
        assert result.data.set_flow_run_states.states[0].message is None
        assert result.data.set_flow_run_states.states[0].status == "QUEUED"

        fr = await models.FlowRun.where(id=second_run).first({"state", "version"})
        assert fr.version == 3
        assert fr.state == "Queued"


# ---------------------------------------------------------------
# Task runs
# ---------------------------------------------------------------


class TestSetTaskRunStates:
    mutation = """
        mutation($input: set_task_run_states_input!) {
            set_task_run_states(input: $input) {
                states {
                    id
                    status
                    message
                }
            }
        }
    """

    async def test_set_task_run_state(
        self, run_query, task_run_id, running_flow_run_id
    ):
        result = await run_query(
            query=self.mutation,
            variables=dict(
                input=dict(
                    states=[dict(task_run_id=task_run_id, state=Running().serialize())]
                )
            ),
        )

        assert result.data.set_task_run_states.states[0].id == task_run_id
        tr = await models.TaskRun.where(id=task_run_id).first({"state", "version"})
        assert tr.version == 2
        assert tr.state == "Running"

    async def test_set_task_run_state_with_version(
        self, run_query, task_run_id, running_flow_run_id
    ):
        result = await run_query(
            query=self.mutation,
            variables=dict(
                input=dict(
                    states=[
                        dict(
                            task_run_id=task_run_id,
                            version=0,
                            state=Running().serialize(),
                        )
                    ]
                )
            ),
        )

        assert result.data.set_task_run_states.states[0].id == task_run_id
        tr = await models.TaskRun.where(id=task_run_id).first({"state", "version"})
        assert tr.version == 2
        assert tr.state == "Running"

    async def test_set_task_run_state_bad_version(self, run_query, locked_task_run_id):
        result = await run_query(
            query=self.mutation,
            variables=dict(
                input=dict(
                    states=[
                        dict(
                            task_run_id=locked_task_run_id,
                            version=100,
                            state=Running().serialize(),
                        )
                    ]
                )
            ),
        )
        assert result.data.set_task_run_states is None
        assert "State update failed" in result.errors[0].message

    async def test_set_multiple_task_run_states(
        self, run_query, task_run_id, task_run_id_2, task_run_id_3, running_flow_run_id
    ):
        result = await run_query(
            query=self.mutation,
            variables=dict(
                input=dict(
                    states=[
                        dict(task_run_id=task_run_id, state=Running().serialize()),
                        dict(task_run_id=task_run_id_2, state=Success().serialize()),
                        dict(
                            task_run_id=task_run_id_3,
                            version=1,
                            state=Retrying().serialize(),
                        ),
                    ]
                )
            ),
        )
        assert result.data.set_task_run_states.states == [
            {"id": task_run_id, "status": "SUCCESS", "message": None},
            {"id": task_run_id_2, "status": "SUCCESS", "message": None},
            {"id": task_run_id_3, "status": "SUCCESS", "message": None},
        ]

        tr1 = await models.TaskRun.where(
            id=result.data.set_task_run_states.states[0].id
        ).first({"state", "version"})
        assert tr1.version == 2
        assert tr1.state == "Running"

        tr2 = await models.TaskRun.where(
            id=result.data.set_task_run_states.states[1].id
        ).first({"state", "version"})
        assert tr2.version == 3
        assert tr2.state == "Success"

        tr3 = await models.TaskRun.where(
            id=result.data.set_task_run_states.states[2].id
        ).first({"state", "version"})
        assert tr3.version == 3
        assert tr3.state == "Retrying"

    async def test_set_multiple_task_run_states_with_one_failed(
        self, run_query, locked_task_run_id, task_run_id_3, running_flow_run_id
    ):
        result = await run_query(
            query=self.mutation,
            variables=dict(
                input=dict(
                    states=[
                        dict(
                            task_run_id=locked_task_run_id,
                            # BAD VERSION
                            version=100,
                            state=Success().serialize(),
                        ),
                        dict(task_run_id=task_run_id_3, state=Retrying().serialize()),
                    ]
                )
            ),
        )

        assert result.data.set_task_run_states is None
        assert (
            f"State update failed for task run ID {locked_task_run_id}"
            in result.errors[0].message
        )

        # this update failed
        tr2 = await models.TaskRun.where(id=locked_task_run_id).first(
            {"state", "version"}
        )
        assert tr2.version == 1
        assert tr2.state == "Pending"

    async def test_set_task_run_state_with_result(self, run_query, task_run_id):
        result = Result(10, result_handler=JSONResultHandler())
        result.store_safe_value()
        state = Success(result=result)

        result = await run_query(
            query=self.mutation,
            variables=dict(
                input=dict(
                    states=[dict(task_run_id=task_run_id, state=state.serialize())]
                )
            ),
        )
        tr = await models.TaskRun.where(
            id=result.data.set_task_run_states.states[0].id
        ).first({"state", "version"})
        assert tr.version == 2
        assert tr.state == "Success"

    async def test_set_task_run_state_with_safe_result(self, run_query, task_run_id):
        result = SafeResult("10", result_handler=JSONResultHandler())
        state = Success(result=result)

        result = await run_query(
            query=self.mutation,
            variables=dict(
                input=dict(
                    states=[dict(task_run_id=task_run_id, state=state.serialize())]
                )
            ),
        )
        tr = await models.TaskRun.where(
            id=result.data.set_task_run_states.states[0].id
        ).first({"state", "version"})
        assert tr.version == 2
        assert tr.state == "Success"

    async def test_set_task_run_state_with_correct_flow_run_state(
        self, run_query, flow_run_id, task_run_id
    ):
        await api.states.set_flow_run_state(
            flow_run_id=flow_run_id, version=1, state=Running()
        )

        result = await run_query(
            query=self.mutation,
            variables=dict(
                input=dict(
                    states=[
                        dict(
                            task_run_id=task_run_id,
                            state=Running().serialize(),
                            flow_run_version=2,
                        )
                    ]
                )
            ),
        )
        tr = await models.TaskRun.where(
            id=result.data.set_task_run_states.states[0].id
        ).first({"state", "version"})
        assert tr.version == 2
        assert tr.state == "Running"

    async def test_set_task_run_state_fails_with_wrong_flow_run_state(
        self, run_query, flow_run_id_2, task_run_id
    ):
        await api.states.set_flow_run_state(
            flow_run_id=flow_run_id_2, version=2, state=Running()
        )

        result = await run_query(
            query=self.mutation,
            variables=dict(
                input=dict(
                    states=[
                        dict(
                            task_run_id=task_run_id,
                            state=Running().serialize(),
                            flow_run_version=5,
                        )
                    ]
                )
            ),
        )
        assert "State update failed" in str(result.errors[0].message)
        tr = await models.TaskRun.where(id=task_run_id).first({"state", "version"})
        assert tr.version == 1
        assert tr.state == "Pending"

    async def test_set_task_run_states_rejects_states_with_large_payloads(
        self, run_query, task_run_id, task_run_id_2, running_flow_run_id
    ):
        result = await run_query(
            query=self.mutation,
            variables=dict(
                input=dict(
                    states=[
                        dict(
                            task_run_id=task_run_id,
                            # this state should successfully set
                            state=Running().serialize(),
                        ),
                        dict(
                            task_run_id=task_run_id_2,
                            # nonsense payload, just large
                            state={
                                i: os.urandom(2 * 1000000).decode("latin")
                                for i in range(2)
                            },
                        ),
                    ]
                )
            ),
        )
        assert "State payload is too large" in result.errors[0].message


class TestCancelFlowRun:
    mutation = """
        mutation($input: cancel_flow_run_input!) {
            cancel_flow_run(input: $input) {
                state
            }
        }
    """

    @pytest.mark.parametrize(
        "state,res_state,version",
        [
            (Running(), "Cancelling", 4),
            (Success(), "Success", 3),
            (Submitted(), "Cancelled", 4),
        ],
    )
    async def test_cancel_flow_run(
        self, run_query, flow_run_id, state, res_state, version
    ):
        await api.states.set_flow_run_state(
            flow_run_id=flow_run_id, version=1, state=state
        )

        result = await run_query(
            query=self.mutation,
            variables={"input": {"flow_run_id": flow_run_id}},
        )

        assert result.data.cancel_flow_run.state == res_state

        fr = await models.FlowRun.where(id=flow_run_id).first({"state", "version"})
        assert fr.version == version
        assert fr.state == res_state
