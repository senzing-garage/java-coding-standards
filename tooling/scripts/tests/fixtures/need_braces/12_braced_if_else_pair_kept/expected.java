public class Foo
{
    public Object method(Object x)
    {
        if (x == null) {
            return null;
        } else {
            return x.toString();
        }
    }
}
