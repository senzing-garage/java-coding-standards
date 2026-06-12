public class Demo
{
    public Object run(Repository registry, Predicate predicate)
    {
        return registry.findAllActiveSubscribers().filter(predicate).build().result.toUpperCase().format();
    }
}
