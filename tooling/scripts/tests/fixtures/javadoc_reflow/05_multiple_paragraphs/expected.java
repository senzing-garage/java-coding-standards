public class Foo
{
    /**
     * The number of milliseconds to sleep between checks on the locks required
     * for tasks that have been postponed.
     *
     * Larger values reduce CPU usage but make stalled tasks take longer to be
     * reaped.
     */
    public int waitMillis;
}
