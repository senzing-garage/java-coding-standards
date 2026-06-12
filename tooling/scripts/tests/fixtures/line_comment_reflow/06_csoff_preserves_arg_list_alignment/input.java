public class Demo
{
    public void run()
    {
        // CSOFF: LineLength
        logInfo("Server status report: ",
                "    Pending Requests : " + this.queue.getPendingCount(),
                "    Active Workers   : " + this.pool.getActiveCount(),
                "    Idle Time        : " + this.computeIdleNanos() / ONE_MILLION + "ms");
        // CSON: LineLength
    }
}
