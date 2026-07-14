public class Demo
{
    private Object proxyEnvironment;

    public void configure(Object environment, Object destroyMethod)
    {
        this.proxyEnvironment = (Object) SomeReflectionUtilities.restrictedProxy(environment, destroyMethod);
    }
}
