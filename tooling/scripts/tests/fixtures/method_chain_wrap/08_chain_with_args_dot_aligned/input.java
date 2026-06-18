public class Demo
{
    public void setUp()
    {
        this.env = MyConfigurableEnvironment.newAutoBuilder().instanceName(instanceName).settings(settings).verboseLogging(false).build();
    }
}
