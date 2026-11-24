public class TaskGroup
{
    void add(Task task)
    {
        // check the task group of the task
        if (task.getTaskGroup() != this) {
            throw new IllegalArgumentException(
                "The specified task does not have this TaskGroup as its group.  "
                + "task=[ " + task + " ], actualGroup=[ "
                + task.getTaskGroup() + " ], expectedGroup=[ " + this + " ]");
        }
    }
}
