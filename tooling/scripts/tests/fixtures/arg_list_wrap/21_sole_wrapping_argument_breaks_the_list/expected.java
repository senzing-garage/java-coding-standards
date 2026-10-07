public class Demo
{
    public void run(Collection<Item> theCollection)
    {
        theCollection.forEach(
            element -> element.someLongMethodName(firstArgument,
                                                  secondArgument,
                                                  thirdArg));
    }
}
