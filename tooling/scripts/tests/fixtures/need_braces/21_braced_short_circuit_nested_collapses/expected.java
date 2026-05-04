public class Foo
{
    public Object method(boolean a, boolean b)
    {
        if (a) {
            if (b) return null;
        }
        return done();
    }
}
