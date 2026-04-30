public class Foo
{
    public void method()
    {
        for (int i = 0; i < 10; i++) {
            if (done(i))
                break;
            doIt(i);
        }
    }
}
