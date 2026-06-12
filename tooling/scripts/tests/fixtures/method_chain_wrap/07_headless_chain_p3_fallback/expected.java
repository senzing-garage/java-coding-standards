public class Demo
{
    public void run()
    {
        var x = findAllRegisteredHandlerInstancesByCategory()
            .filterByActiveStatus(predicate)
            .sorted()
            .toList();
    }
}
