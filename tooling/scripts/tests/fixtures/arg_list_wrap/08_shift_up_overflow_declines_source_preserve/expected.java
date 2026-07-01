public class Demo
{
    public void run()
    {
        try {
            somePool = new SomePoolClass(connector, minPoolSize, maxPoolSize,
                                         expireSeconds, retireLimit,
                                         moreExtraParam);
        } catch (Exception e) {
        }
    }
}
