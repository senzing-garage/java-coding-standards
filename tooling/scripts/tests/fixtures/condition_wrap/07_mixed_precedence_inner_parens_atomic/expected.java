public class Demo
{
    private static final long ONE_THOUSAND = 1000L;
    private static final long ONE_MILLION = 1000000L;

    public long computeDelay(java.time.Duration duration)
    {
        return duration.getSeconds() * ONE_THOUSAND
            + (duration.getNano() / ONE_MILLION);
    }
}
