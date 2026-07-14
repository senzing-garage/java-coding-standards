public class Demo
{
    public Object build()
    {
        Object result = (new SomeLongerServiceClass(argOne, argTwo)
                             .chain1(x)
                             .chain2(y)
                             .finish());
        return result;
    }
}
