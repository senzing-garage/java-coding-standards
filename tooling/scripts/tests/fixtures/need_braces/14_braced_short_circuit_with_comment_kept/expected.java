public class Foo
{
    public Object method(Object x)
    {
        if (x == null) {
            // explain why we bail here
            return null;
        }
    }
}
